"""The calibration thread: step the phase DAC, record a sweep at each step, fit the voltage-to-angle map.

The thread uses the box the way the Tune tab does and nothing more:
- one tune-mode DAQConnection for the whole calibration;
- each DAC change is the Tune latch sequence, set_dac(v, 0) then set_dac(v, 1);
- each chunk is one tune-mode chunk (tune_per_chunk sweeps), started with start_sweeps;
- a stop request ends the calibration after the current chunk.
When it finishes, stops or fails, it puts the DAC back to the tune the Tune tab shows.
"""
import datetime
import math
import subprocess
import time

import numpy as np

from core.thread_manager import BaseThread
from hardware import DAQConnection

from . import calfit
from .records import CAL_SCHEMA, write_calibration


def git_sha():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


class CalibrationThread(BaseThread):
    """Phase-DAC calibration.

    Args:
        config: the Config in use (channel, frequency list, fpga settings)
        cal: the 'cal' settings dict
        tunes: {angle: vout} operator tunes; tunes[0] is the reference for angles
        restore_vout: DAC value to leave the box at
        profile: -p profile name, for the record

    Signals:
        reply: {'step': i, 'of': n, 'vout': v} during the scan, then {'done': True, 'record': dict}
    """

    def __init__(self, config, cal, tunes, restore_vout, profile=None, out_dir=None):
        stamp = int(time.time() * 1e6)
        super().__init__(name=f'quad_cal_{stamp}', parent=None, config=config)
        self.cal = dict(cal)
        self.tunes = {int(a): float(v) for a, v in tunes.items() if v is not None}
        self.restore_vout = float(restore_vout)
        self.profile = profile
        self.out_dir = out_dir          # where the record is saved (during the scan, before and after the fit)
        self.path = None
        self.daq = None
        self.record = None
        self._dac = None

    # -- box access ---------------------------------------------------------
    def _set_phase(self, v):
        '''Tune-tab latch sequence; returns the box's answer to the real write'''
        self.daq.set_dac(v, 0)
        ok = bool(self.daq.set_dac(v, 1))
        self._dac = v
        return ok

    def _chunk(self):
        '''One tune-mode chunk: (num, phase, diode)'''
        n_per = self.config.settings['tune_per_chunk']
        self.daq.start_sweeps()
        sigs = self.daq.get_chunk()
        while sigs[1] < n_per:
            if self.should_stop():
                break
            sigs = self.daq.get_chunk()
        return sigs[1], np.asarray(sigs[2], dtype=float), np.asarray(sigs[3], dtype=float)

    def _acquire(self, n_chunks):
        num, phase, diode = 0, None, None
        for _ in range(n_chunks):
            n, p, d = self._chunk()
            if n <= 0:
                continue
            num += n
            phase = p if phase is None else phase + (n / num) * (p - phase)
            diode = d if diode is None else diode + (n / num) * (d - diode)
            if self.should_stop():
                break
        return num, phase, diode

    def _save(self):
        '''Write the record as it stands, so a stop, crash or close never loses the steps taken'''
        if self.out_dir is None or self.record is None:
            return
        try:
            self.path = write_calibration(self.record, self.out_dir)
        except Exception as e:
            self._logger.error(f'Could not save the calibration record: {e}')

    # -- thread ---------------------------------------------------------------
    def setup(self):
        self.daq = DAQConnection(self.config, self.config.settings['fpga_settings']['timeout_tune'], True)

    def execute(self):
        start = datetime.datetime.now(tz=datetime.timezone.utc)
        t0 = time.monotonic()
        cal = self.cal
        channel = self.config.channel
        n_per = int(self.config.settings['tune_per_chunk'])
        n_chunks = max(1, math.ceil(int(cal['sweeps_per_step']) / n_per))
        settle_s = float(cal['settle_ms']) / 1000.0
        plan = calfit.step_plan(cal, self.tunes[0], [v for a, v in self.tunes.items() if a != 0])
        rec = {
            'record_type': 'quad_calibration', 'schema': CAL_SCHEMA,
            'cal_id': start.strftime('%Y-%m-%d_%H-%M-%S'),
            'start_time': str(start), 'start_stamp': start.timestamp(),
            'profile': self.profile, 'daq_type': self.config.settings.get('daq_type'),
            'channel': channel.get('name'), 'species': channel.get('species'),
            'cent_freq': channel.get('cent_freq'), 'mod_freq': channel.get('mod_freq'),
            'freq_list': np.asarray(self.config.freq_list, dtype=float).tolist(),
            'diode_vout': self.config.diode_vout,
            'tunes': {str(a): v for a, v in self.tunes.items()},
            'restore_vout': self.restore_vout,
            'settings': cal, 'settle_ms': float(cal['settle_ms']),
            'sweeps_per_step': n_chunks * n_per, 'tune_per_chunk': n_per,
            'pynmr_git': git_sha(),
            'steps': [], 'settle_test': None, 'fit': None, 'status': 'running', 'error': None,
        }
        self.record = rec
        try:
            for i, step in enumerate(plan):
                if self.should_stop():
                    rec['status'] = 'stopped'
                    break
                ok = self._set_phase(step['vout'])
                time.sleep(settle_s)
                t_step = time.monotonic() - t0
                num, phase, diode = self._acquire(n_chunks)
                rec['steps'].append({'order': i, 'vout': step['vout'], 'pass': step['pass'], 'kind': step['kind'],
                                     't_s': t_step, 'stamp': time.time(), 'dac_ok': ok, 'num': int(num),
                                     'phase': None if phase is None else phase.tolist(),
                                     'diode': None if diode is None else diode.tolist()})
                if (i + 1) % 10 == 0:
                    self._save()
                self.emit_reply({'step': i + 1, 'of': len(plan), 'vout': step['vout'], 't_s': time.monotonic() - t0,
                                 'kind': step['kind'],
                                 'mean_phase': None if phase is None else float(np.mean(phase)),
                                 'mean_diode': None if diode is None else float(np.mean(diode))})
            if rec['status'] == 'running' and int(cal.get('settle_test_chunks', 0)) > 0:
                rec['settle_test'] = self._settle_test(int(cal['settle_test_chunks']), settle_s)
        except Exception as e:
            rec['status'] = 'error'
            rec['error'] = str(e)
            self._logger.error(f'Phase calibration failed: {e}')
            try:
                self.daq.abort()          # make sure the box is not left sweeping
            except Exception as e2:
                self._logger.warning(f'Could not send stop to the DAQ: {e2}')
        self._restore()
        good = [s for s in rec['steps'] if s['phase'] is not None and s['dac_ok']]
        if self.should_stop() and rec['status'] == 'running':
            rec['status'] = 'stopped'
        if rec['status'] == 'running':
            rec['status'] = 'ok'
        self._save()
        real_steps = [s for s in good if abs(s['vout'] - self.tunes[0]) < 1e-6]
        if rec['status'] == 'stopped':
            # PyNMR waits only 3 s for threads at exit, then kills them (which crashes Python), so a stop
            # never waits for the fit. The steps are saved; refit them offline with calfit.fit_calibration.
            rec['fit'] = {'success': False, 'message': 'stopped before the fit; the steps are saved for an offline refit'}
        elif len(good) >= 5 and real_steps:
            self.emit_reply({'stage': 'fitting', 'steps': len(good)})
            try:
                rec['fit'] = calfit.fit_calibration(
                    [s['vout'] for s in good], [s['t_s'] for s in good], [s['phase'] for s in good],
                    self.tunes[0], tunes=self.tunes, gain_order=int(cal['gain_order']),
                    offset_order=int(cal['offset_order']), fit_drift=bool(cal['fit_drift']), bins=int(cal['bins']),
                    v_range=(float(cal['v_min']), float(cal['v_max'])))
            except Exception as e:
                rec['fit'] = {'success': False, 'message': f'fit failed: {e}'}
        else:
            rec['fit'] = {'success': False, 'message': f'only {len(good)} usable steps'}
        stop = datetime.datetime.now(tz=datetime.timezone.utc)
        rec['stop_time'], rec['stop_stamp'] = str(stop), stop.timestamp()
        self._save()
        self.emit_reply({'done': True, 'record': rec, 'path': self.path})

    def _settle_test(self, chunks, settle_s):
        '''Jump v_min -> v_max and record back-to-back chunks; diagnostic only'''
        lo, hi = float(self.cal['v_min']), float(self.cal['v_max'])
        self._set_phase(lo)
        time.sleep(settle_s)
        self._acquire(1)
        self._set_phase(hi)
        t_write = time.monotonic()
        t_ms, means = [], []
        for _ in range(chunks):
            if self.should_stop():
                break
            n, p, _ = self._chunk()
            t_ms.append((time.monotonic() - t_write) * 1000.0)
            means.append(float(np.mean(p)))
        out = calfit.settle_fit(t_ms, means)
        out.update({'from_vout': lo, 'to_vout': hi, 'chunk_sweeps': int(self.config.settings['tune_per_chunk'])})
        return out

    def _restore(self):
        if self.daq is None:
            return
        try:
            if not self._set_phase(self.restore_vout):
                self._logger.error(f'The box did not accept the phase DAC restore to {self.restore_vout:.4f}.')
        except Exception as e:
            self._logger.error(f'Could not restore the phase DAC to {self.restore_vout:.4f}: {e}')

    def cleanup(self):
        if self.daq is not None:
            if self._dac is not None and self.record is None:
                self._restore()
            close = getattr(self.daq, 'close', None)   # clean close once daq-link is merged
            try:
                if close:
                    close()
            except Exception as e:
                self._logger.warning(f'Error closing the DAQ connection: {e}')
            self.daq = None


class AutoTuneThread(CalibrationThread):
    """Auto Tune (unh/quadrature/autotune.py): short phase-DAC scans around the operator's tunes, then the
    tunes moved to the true 0/90/180/270 deg. A pass is repeated, centred on the new tunes, while a target
    lies outside the steps around its tune (at most autotune max_passes). Box access as for the calibration.

    Args:
        config, cal, tunes, restore_vout, profile, out_dir: as CalibrationThread (cal gives the DAC range)
        at: the 'autotune' settings dict
        selected: the angle shown on the Tune tab; if Auto Tune succeeds the DAC is left on its new tune

    Signals:
        reply: {'step', 'of', 'pass', 'vout', ...} during the scans, {'stage': 'fitting', ...} before each fit,
        then {'autotune_done': True, 'record': dict, 'path': str}
    """

    def __init__(self, config, cal, tunes, restore_vout, at, selected=0, profile=None, out_dir=None):
        super().__init__(config, cal, tunes, restore_vout, profile=profile, out_dir=out_dir)
        self.at = dict(at)
        self.selected = int(selected)

    def _pass(self, n, centres, offsets, cfg, freqs, v_range, n_chunks, settle_s, t0, kind):
        """One Auto Tune pass: the steps around ``centres`` and their fit (autotune.analyse_pass).

        Returns:
            the analysis dict, or None if the pass was stopped or its fit failed (rec status and error set)
        """
        from . import autotune
        rec = self.record
        plan = autotune.step_plan(centres, offsets, *v_range)
        steps = []
        for i, step in enumerate(plan):
            if self.should_stop():
                rec['status'] = 'stopped'
                break
            ok = self._set_phase(step['vout'])
            time.sleep(settle_s)
            t_step = time.monotonic() - t0
            num, phase, diode = self._acquire(n_chunks)
            steps.append({'order': i, 'vout': step['vout'], 'angle': step['angle'], 'kind': step['kind'],
                          't_s': t_step, 'stamp': time.time(), 'dac_ok': ok, 'num': int(num),
                          'phase': None if phase is None else phase.tolist(),
                          'diode': None if diode is None else diode.tolist()})
            self.emit_reply({'step': i + 1, 'of': len(plan), 'pass': n, 'polish': kind == 'polish',
                             'vout': step['vout'], 't_s': time.monotonic() - t0, 'kind': step['kind'],
                             'mean_phase': None if phase is None else float(np.mean(phase)),
                             'mean_diode': None if diode is None else float(np.mean(diode))})
        this = {'pass': n, 'kind': kind, 'centres': {str(a): v for a, v in centres.items()},
                'offsets': list(offsets), 'steps': steps, 'analysis': None}
        rec['passes'].append(this)
        if rec['status'] == 'stopped':
            return None
        good = [s for s in steps if s['phase'] is not None and s['dac_ok']]
        self.emit_reply({'stage': 'fitting', 'steps': len(good), 'pass': n, 'polish': kind == 'polish'})
        try:
            res = autotune.analyse_pass(good, freqs, centres, cfg, v_range)
        except Exception as e:
            res = {'success': False, 'message': f'fit failed: {e}'}
        this['analysis'] = res
        self._save()
        if not res.get('success'):
            rec['status'] = 'failed'
            rec['error'] = res.get('message')
            return None
        return res

    def execute(self):
        from . import autotune
        start = datetime.datetime.now(tz=datetime.timezone.utc)
        t0 = time.monotonic()
        at = self.at
        channel = self.config.channel
        n_per = int(self.config.settings['tune_per_chunk'])
        n_chunks = max(1, math.ceil(int(at['sweeps_per_step']) / n_per))
        settle_s = float(at['settle_ms']) / 1000.0
        v_range = (float(self.cal['v_min']), float(self.cal['v_max']))
        freqs = np.asarray(self.config.freq_list, dtype=float)
        cfg = dict(at, ref_MHz=float(channel.get('cent_freq', 0.5 * (freqs.min() + freqs.max()))))
        rec = {
            'record_type': 'quad_autotune', 'schema': CAL_SCHEMA,
            'cal_id': 'autotune_' + start.strftime('%Y-%m-%d_%H-%M-%S'),
            'start_time': str(start), 'start_stamp': start.timestamp(),
            'profile': self.profile, 'daq_type': self.config.settings.get('daq_type'),
            'channel': channel.get('name'), 'species': channel.get('species'),
            'cent_freq': channel.get('cent_freq'), 'mod_freq': channel.get('mod_freq'),
            'freq_list': freqs.tolist(), 'diode_vout': self.config.diode_vout,
            'hand_tunes': {str(a): v for a, v in self.tunes.items()},
            'settings': cfg, 'sweeps_per_step': n_chunks * n_per, 'tune_per_chunk': n_per,
            'pynmr_git': git_sha(), 'passes': [], 'result': None, 'status': 'running', 'error': None,
        }
        self.record = rec
        centres = dict(self.tunes)
        try:
            for n in range(1, int(at['max_passes']) + 1):
                res = self._pass(n, centres, at['offsets'], cfg, freqs, v_range, n_chunks, settle_s, t0, 'main')
                if res is None:
                    break
                new = {int(a): t['to_vout'] for a, t in res['tunes'].items()}
                if not res['converged']:
                    centres = new
                    continue
                final, polish = res, None
                if at.get('polish', True):
                    # polish: tighter steps around the new tunes, measuring the new tunes themselves
                    pol = self._pass(n + 1, new, at['polish_offsets'], dict(cfg, offsets=at['polish_offsets']),
                                     freqs, v_range, n_chunks, settle_s, t0, 'polish')
                    if pol is not None and pol['converged']:
                        final = pol
                        new = {int(a): t['to_vout'] for a, t in pol['tunes'].items()}
                        polish = {'used': True, 'moved_deg': {a: t['moved_deg'] for a, t in pol['tunes'].items()}}
                    else:
                        rec['status'], rec['error'] = 'running', None   # a stopped or failed polish keeps the main result
                        polish = {'used': False, 'message': (pol or {}).get('message') or
                                  ('stopped' if self.should_stop() else 'a target outside the polish steps')}
                first = rec['passes'][0]['analysis']['tunes']
                rec['result'] = {
                    'tunes': {str(a): v for a, v in new.items()},
                    'hand_error_deg': {a: -t['moved_deg'] for a, t in first.items()},
                    'gain_ratio': {a: t['gain_ratio'] for a, t in final['tunes'].items()},
                    'theta_ref_err_deg': final['trace']['theta_ref_err_deg'],
                    'arc_deg': final['trace']['arc_deg'], 'ref_MHz': final['trace']['ref_MHz'],
                    'residual_rel': final['trace']['residual_rel'], 'passes': n, 'polish': polish,
                }
                rec['status'] = 'ok'
                if self.selected in new:
                    self.restore_vout = float(new[self.selected])
                break
            if rec['status'] == 'running':
                rec['status'] = 'not converged'
                rec['error'] = (f"a target was still outside the steps after {at['max_passes']} passes; "
                                'set the tunes closer by hand and try again')
        except Exception as e:
            rec['status'] = 'error'
            rec['error'] = str(e)
            self._logger.error(f'Auto Tune failed: {e}')
            try:
                self.daq.abort()
            except Exception as e2:
                self._logger.warning(f'Could not send stop to the DAQ: {e2}')
        self._restore()
        stop = datetime.datetime.now(tz=datetime.timezone.utc)
        rec['stop_time'], rec['stop_stamp'] = str(stop), stop.timestamp()
        self._save()
        self.emit_reply({'autotune_done': True, 'record': rec, 'path': self.path})
