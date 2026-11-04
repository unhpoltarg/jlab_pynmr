"""Glue between PyNMR and the quadrature feature.

MainWindow calls attach_quadrature() once, after its tabs exist. When the feature is enabled for the
profile, that sets ``main_window.quadrature`` to a QuadController. The UNH-HOOK quad-phase blocks in the
JLab files call it only through ``getattr(..., 'quadrature', None)``:

    RunTab.start_thread    before_event() before new_event(), tag_event() after it
    RunThread.execute      after_sweeps(): with an event's sweeps all in, writes the next event's tune (run thread)
    RunTab.finish_run      run_finished(): back to the Real tune
    MainWindow             set_event_base(), is_real() (EPICS and history), save_session()
    BaseTab                baselines per reference angle

When the feature is off, nothing is attached and every hook is a no-op.
"""
import logging
import os
import time

import numpy as np

from config import Config
from core import Baseline, EventType

from . import records
from .scheduler import Scheduler
from .settings import load_settings, sequence_of

log = logging.getLogger('PyNMR.unh.quadrature')

SESSION_KEYS = {90: 'phase_tune_q', 180: 'phase_tune_180', 270: 'phase_tune_270'}


class QuadController:
    """Quadrature state for one MainWindow.

    Args:
        main_window: the PyNMR MainWindow
        cfg: settings from settings.load_settings
    """

    def __init__(self, main_window, cfg):
        self.mw = main_window
        self.cfg = cfg
        self.sched = Scheduler(sequence_of(cfg), cfg['settle_ms'])
        restore = getattr(main_window, 'restore_dict', None) or {}
        self.sched.tunes[0] = float(main_window.config.phase_vout)
        for angle, key in SESSION_KEYS.items():
            if restore.get(key) is not None:
                self.sched.tunes[angle] = float(restore[key])
        self.use_default_tunes()
        self.selected = 0            # tune shown and edited on the Tune tab
        self.current = None          # Assignment of the event being taken
        self.in_run = False
        self.baselines = {}          # angle -> Baseline taken at that angle
        self.last_real = None        # (pol, area) of the last Real record, for the Run-tab indicators
        self.cal_thread = None
        self.cal_dir = os.path.join(main_window.config.settings['event_dir'], cfg['cal']['out_dir'])
        self.sched.calibration = records.latest_calibration(self.cal_dir, main_window.config.channel.get('name'))
        self.fpga = 'NIDAQ' not in str(main_window.config.settings.get('daq_type', ''))
        self.ui = None

    def use_default_tunes(self):
        """Start from quadrature.yaml's default_tunes when the session has no usable set: a tune is missing, at
        DAC 0 % (never set) or on the Real tune. A usable saved set (the operator's latest) is kept."""
        defaults = {int(a): float(v) for a, v in (self.cfg.get('default_tunes') or {}).items()}
        if 0 not in defaults:
            return False
        t = self.sched.tunes
        unset = lambda v: v is None or abs(v) < 1e-6
        usable = not unset(t.get(0)) and all(not unset(t.get(a)) and abs(t[a] - t[0]) >= 0.01
                                             for a in defaults if a != 0)
        if usable:
            return False
        for a, v in defaults.items():
            t[a] = v
        self.mw.config.phase_vout = defaults[0]
        tune = getattr(self.mw, 'tune_tab', None)
        if tune is not None:
            tune.phase_spin.setValue(defaults[0] * 100)     # shows it; JLab's slot also sends it to the box
        log.info('Quadrature: no usable saved tunes, so starting from default_tunes: ' +
                 ', '.join(f'{a} deg at DAC {v * 100:.2f} %' for a, v in sorted(defaults.items())) + '.')
        return True

    # -- status --------------------------------------------------------------
    def message(self, text, level=logging.INFO):
        log.log(level, text)
        bar = getattr(self.mw, 'status_bar', None)
        if bar is not None:
            bar.showMessage(text)

    def calibrating(self):
        return self.cal_thread is not None and self.cal_thread.isRunning()

    # -- operator controls (GUI thread) --------------------------------------
    def set_active(self, on):
        """Quadrature checkbox. Returns the state actually set."""
        if on:
            self.fill_opposites()
            problem = None
            if not self.fpga:
                problem = 'this DAQ has no phase DAC'
            elif self.sched.missing_tunes():
                names = ', '.join('Imag' if a == 90 else f'{a} deg' for a in self.sched.missing_tunes())
                problem = f'set the {names} Phase Tune on the Tune tab first'
            else:
                for a in set(self.sched.sequence) - {0}:
                    if self.sched.same(self.sched.tunes[a], self.sched.tunes[0]):
                        name = ANGLE_LABELS.get(a, f'{a} deg')
                        problem = (f'the {name} ({a} deg) tune is set to the same phase DAC value as the Real '
                                   f'(0 deg) tune (DAC {self.sched.tunes[0] * 100:.2f} %); set it on the Tune tab')
            if problem:
                self.message(f'Quadrature not turned on: {problem}.', logging.WARNING)
                on = False
            self.refusal = problem       # shown beside the checkbox, which otherwise just snaps back
        self.sched.active = bool(on)
        if on:
            self.update_context()
            valid = self.sched.calibration_valid()
            self.message('Quadrature on: events alternate ' + ', '.join(f'{a}' for a in self.sched.sequence) +
                         ' deg.' + ('' if valid else ' No current calibration for these tunes; the angle is not'
                                                     ' recorded until one is taken.'))
        return self.sched.active

    def fill_opposites(self):
        """For cycle4: set a missing 180 deg tune opposite Real and a missing 270 deg tune opposite Imag, from the
        latest calibration's phase table (the opposite nearest the tune it pairs with). Opposite settings don't
        depend on the calibration's gain assumption; 180 deg is still easy to fine-tune by eye."""
        fit = (self.sched.calibration or {}).get('fit') or {}
        table = fit.get('phi_table')
        if not table or not fit.get('success'):
            return
        v_tab = np.asarray(table['vout'], dtype=float)
        p_tab = np.unwrap(np.radians(table['phi_deg']))
        hi = fit.get('clip_vout') or v_tab.max()
        live = v_tab <= hi + 1e-9
        v_tab, p_tab = v_tab[live], np.degrees(p_tab[live])
        filled = []
        for angle, partner in ((180, 0), (270, 90)):
            if angle not in self.sched.sequence or self.sched.tunes.get(angle) is not None:
                continue
            v_partner = self.sched.tunes.get(partner)
            if v_partner is None:
                continue
            p_partner = float(np.interp(v_partner, v_tab, p_tab))
            dense = np.linspace(v_tab.min(), v_tab.max(), 20001)
            phi = np.interp(dense, v_tab, p_tab)
            best = None
            for target in (p_partner + 180.0, p_partner - 180.0):
                hits = np.nonzero(np.diff(np.sign(phi - target)))[0]
                for i in hits:
                    v = dense[i] + (target - phi[i]) * (dense[i + 1] - dense[i]) / (phi[i + 1] - phi[i])
                    if best is None or abs(v - v_partner) < abs(best - v_partner):
                        best = v
            if best is not None:
                self.sched.tunes[angle] = round(float(best), 4)
                filled.append(f'{angle} deg at DAC {best * 100:.2f} %')
        if filled:
            self.message('Set from the calibration (opposite the Real and Imag tunes): ' + ', '.join(filled) +
                         '. Fine-tune 180 deg by eye on the Tune tab if needed.')
            if self.ui:
                self.ui.refresh()

    def update_context(self):
        """Tell the scheduler which channel and centre frequency are in use (calibration validity)."""
        ch = self.mw.config.channel
        self.sched.context = {'channel': ch.get('name'), 'cent_freq': ch.get('cent_freq')}

    def set_sequence(self, seq):
        self.sched.sequence = list(seq)

    def select_tune(self, angle):
        """Tune-tab selector: show and edit the tune for ``angle``. The spinbox sends it to the box."""
        self.selected = int(angle)
        v = self.sched.tunes.get(self.selected)
        if v is None:
            v = self.sched.tunes[0]
            self.sched.tunes[self.selected] = v
        spin = self.mw.tune_tab.phase_spin
        spin.setValue(v * 100)       # JLab's slot sets config.phase_vout and the DAC; ours stores the value
        if self.ui:
            self.ui.refresh()

    def tune_spin_changed(self, value_percent):
        """Connected after JLab's own slot on the Tune-tab Phase Tune spinbox."""
        if self.in_run:
            return
        self.sched.tunes[self.selected] = float(value_percent) / 100.0
        if self.ui:
            self.ui.refresh()

    def use_suggested(self, angle):
        """Set the tune for ``angle`` to the calibration's suggestion for +angle or -angle, whichever is nearer
        the tune's present value (both are the same quadrature; the sign only flips it)."""
        cal = self.sched.calibration or {}
        sug = (cal.get('fit') or {}).get('suggested_vout') or {}
        here = self.sched.tunes.get(angle)
        if here is None:
            here = self.sched.tunes[0]
        options = [v for v in (sug.get(str(angle)), sug.get(str(-angle))) if v is not None]
        v = min(options, key=lambda c: abs(c - here)) if options else None
        if v is None:
            self.message(f'The calibration found no DAC value for {angle} deg in the scanned range.', logging.WARNING)
            return
        self.select_tune(angle)
        self.mw.tune_tab.phase_spin.setValue(round(v * 100, 2))

    # -- run loop hooks --------------------------------------------------------
    def before_event(self):
        """RunTab.start_thread, before new_event(): pick this event's tune and use a Config with it."""
        if not self.in_run:
            self.in_run = True
            self._wrote_this_run = False
            self._absorption = {}            # KK reference: only this run's absorption
            self.areas = {}                  # Run-tab Signal Area per angle: this run's records only
            self.sched.start_run()
            if self.ui:
                self.ui.refresh()
        was_suspended = self.sched.suspended
        self.update_context()
        a = self.sched.next_assignment(self.mw.config.phase_vout)
        if self.sched.suspended and not was_suspended:
            self.message(f'Quadrature suspended: {self.sched.suspended}.', logging.ERROR)
        if not self.sched.same(a.vout, self.mw.config.phase_vout):
            new = Config(dict(self.mw.config.channel), self.mw.settings)
            self.mw.replace_config(new)                  # keeps controls and diode_vout
            new.phase_vout = a.vout                      # new Config, not yet used by any event
        if a.write_dac:
            if self.sched.same(self.sched._dac_vout, a.vout):
                a.dac_ok = self.sched._last_ok           # set at the end of the previous event
                how = 'end of previous event'
            else:
                ok = self._write_now(a.vout)             # first event of the run, or after an error
                self.sched.dac_written(a, ok)
                self._wrote_this_run = True
                how = 'before the event (Tune-style connection)'
                if self.sched.suspended and not was_suspended:
                    self.message(f'Quadrature suspended: {self.sched.suspended}.', logging.ERROR)
            if a.tags:
                a.tags['quad_dac_ok'] = a.dac_ok
                a.tags['quad_dac_set'] = how
        self.current = a
        return a

    def _write_now(self, vout):
        """Set the phase DAC with a short tune-mode connection, the way the Tune tab's send_to_dac does, then wait
        settle_ms. Used only when the box does not already hold the tune (run start, or after a failed event)."""
        from hardware import DAQConnection
        ok = False
        daq = None
        try:
            daq = DAQConnection(self.mw.config, 4, True)
            ok = bool(daq.set_dac(vout, 1))      # fresh connection: channel word 0 -> 1 latches
        except Exception as e:
            log.error(f'Quadrature: phase DAC write failed: {e}')
        finally:
            close = getattr(daq, 'close', None)
            if close:
                try:
                    close()
                except Exception as e:
                    log.warning(f'Quadrature: error closing the DAC connection: {e}')
            del daq
        time.sleep(self.sched.settle_ms / 1000.0)
        log.info(f'Quadrature: phase DAC {vout:.4f} {"set" if ok else "NOT accepted"} before the event.')
        return ok

    def tag_event(self, event):
        """RunTab.start_thread, after new_event(): put the quad_* fields on the event."""
        a = self.current
        if a is None:
            return
        a.event = event
        tags = dict(a.tags)
        if hasattr(event, 'quad_base_ref_deg'):
            tags.pop('quad_base_ref_deg', None)          # set by set_event_base
        records.tag_event(event, tags)

    def after_sweeps(self, daq, completed, logger=None):
        """RunThread.execute, after the chunk loop (run thread): put the NEXT event's tune on the box now, on this
        still-open connection, with the Tune tab's latch sequence. The box is idle (all sweeps received), and the
        next event's fresh connection leaves the DAC alone, as in any normal run.

        Why not in RunThread.setup: re-sending the register on the run connection before its sweeps made the box
        stop after the first chunk (two 640-sweep events on 2026-10-27, both with that write; 101 one-chunk events
        were fine). The first event of a run gets its tune from a short Tune-style connection (_write_now).
        """
        a = self.current
        if a is None or not a.tags:
            return
        if not completed:
            self.sched._dac_vout = None       # unknown after an aborted or failed event: next event writes first
            return
        v = self.sched.peek_next()
        if v is None or self.sched.same(v, self.sched._dac_vout):
            return
        ok = False
        try:
            daq.set_dac(v, 0)
            ok = bool(daq.set_dac(v, 1))
        except Exception as e:
            (logger or log).error(f'Quadrature: phase DAC write after the sweeps failed: {e}')
        time.sleep(self.sched.settle_ms / 1000.0)
        self.sched.box_written(v, ok)
        self._wrote_this_run = True
        (logger or log).info(f'Quadrature: phase DAC {v:.4f} {"set" if ok else "NOT accepted"} for the next event.')

    def run_finished(self):
        """RunTab.finish_run: leave the Config and the box on the Real tune."""
        self.in_run = False
        self.current = None
        real = self.sched.tunes[0]
        if real is not None:
            if not self.sched.same(self.mw.config.phase_vout, real):
                new = Config(dict(self.mw.config.channel), self.mw.settings)
                self.mw.replace_config(new)
                new.phase_vout = real
            box = self.sched._dac_vout
            wrote = getattr(self, '_wrote_this_run', False)
            if wrote and (box is None or not self.sched.same(box, real)):
                try:
                    self.mw.tune_tab.send_to_dac(real, 1)
                    self.sched._dac_vout = real
                except Exception as e:
                    self.message(f'Quadrature: could not put the phase DAC back to the Real tune: {e}', logging.ERROR)
        self.selected = 0
        if self.ui:
            self.ui.show_selected_quietly()
            self.ui.refresh()

    # -- baselines ---------------------------------------------------------------
    def set_event_base(self, event, global_baseline):
        """MainWindow.set_event_base, after JLab's lines: an event at another angle gets that angle's baseline.

        Records which baseline was used (quad_base_ref_deg), the phase DAC it was taken at (quad_base_vout) and
        whether that matches this event's tune (quad_base_match)."""
        a = self.current
        if a is None or not a.tags:
            return
        b = self.baselines.get(a.angle)
        if b is not None:
            event.base_stamp = b.stop_stamp
            event.base_time = b.stop_time
            event.base_file = b.base_file
            event.baseline = b.phase
            event.quad_base_ref_deg = a.angle
            used = b
        else:
            event.quad_base_ref_deg = getattr(global_baseline, 'quad_ref_deg', None)
            used = global_baseline
        vout = getattr(used, 'phase_vout', None)
        event.quad_base_vout = None if vout is None else float(vout)
        event.quad_base_match = bool(b is not None and records.same_vout(vout, a.vout))

    def new_baselines(self, by_angle):
        """BaseTab.set_base: store one baseline per reference angle (dicts from records.group_baselines)."""
        self.baselines = {}
        for angle, d in by_angle.items():
            self.baselines[int(angle)] = Baseline(self.mw.config, d)
        parts = [f"{a} deg ({len(by_angle[a].get('base_stamps', []))} rows, {by_angle[a].get('sweeps', 0)} sweeps)"
                 for a in sorted(by_angle)]
        text = 'Quadrature baselines set: ' + ', '.join(parts) + '.'
        missing = [a for a in self.sched.sequence if a not in by_angle]
        if missing:
            text += (' No baseline for ' + ', '.join(f'{a} deg' for a in sorted(set(missing))) +
                     '; those events use the 0 deg baseline.')
        self.message(text, logging.WARNING if missing else logging.INFO)
        if self.ui:
            self.ui.refresh()

    def clear_baselines(self):
        """An untagged baseline was set: drop the per-angle ones, so every angle uses it (and the status says so)."""
        if self.baselines:
            self.baselines = {}
            self.message('Per-angle quadrature baselines cleared: an untagged baseline was set for all angles.',
                         logging.WARNING)
        if self.ui:
            self.ui.refresh()

    def baseline_status(self):
        """[(angle, state)] for the angles of the sequence: 'ok', 'none' (falls back to the 0 deg baseline),
        'other tune' (taken at another phase DAC setting), or 'not set' for 0 deg with no baseline at all."""
        out = []
        main = getattr(self.mw, 'baseline', None)
        for angle in sorted(set(self.sched.sequence) | {0}):
            b = self.baselines.get(angle)
            if b is None and angle == 0 and main is not None and getattr(main, 'stop_stamp', 0):
                b = main
            if b is None:
                out.append((angle, 'not set' if angle == 0 else 'none'))
                continue
            vout = getattr(b, 'phase_vout', None)
            tune = self.sched.tunes.get(angle)
            if vout is None:
                out.append((angle, 'ok' if angle == 0 else 'untagged'))
            elif tune is not None and not records.same_vout(vout, tune):
                out.append((angle, 'other tune'))
            else:
                out.append((angle, 'ok'))
        return out

    # -- downstream --------------------------------------------------------------
    @staticmethod
    def is_real(event):
        return records.is_real(event)

    def on_event_finished(self, bus_data):
        """After the Run tab has shown a record: keep the big pol indicator on the last Real record."""
        event = bus_data.get('event')
        if event is None:
            return
        self._keep_absorption(event)
        if getattr(event, 'quad_ref_deg', None) is not None:
            try:
                self.latest_raw = getattr(self, 'latest_raw', {})
                self.latest_raw[records.angle_of(event)] = (np.asarray(event.scan.freq_list, dtype=float),
                                                            np.asarray(event.scan.phase, dtype=float))
            except (AttributeError, TypeError, ValueError):
                pass
        if self.ui:
            self.ui.plots.show_event(event)
            self.ui.base_refresh()
        tab = getattr(self.mw, 'run_tab', None)
        tagged = getattr(event, 'quad_ref_deg', None) is not None
        if tagged:
            self.areas = getattr(self, 'areas', {})
            self.areas[records.angle_of(event)] = getattr(event, 'area', float('nan'))
        if records.is_real(event):
            self.last_real = (event.pol, event.area)
        elif tab is not None and self.last_real is not None:
            tab.pol_value.setText('{:.2%}'.format(self.last_real[0]))
        if tab is not None and tagged and self.sched.active:
            tab.area_value.setText(self.area_lines())

    def area_lines(self):
        """Run tab Signal Area in quadrature: one line per angle of the sequence, each from its own latest record."""
        lines = []
        for a in sorted(set(self.sched.sequence) | {0}):
            v = getattr(self, 'areas', {}).get(a)
            lines.append(f'{a}°: ' + ('waiting' if v is None else f'{v:.6f}'))
        return '<div style="font-size:13pt">' + '<br>'.join(lines) + '</div>'

    # -- dispersive records -------------------------------------------------------
    def _keep_absorption(self, event):
        """Remember the latest 0 deg and 180 deg fit-subtracted lines as the absorption for KK."""
        angle = records.angle_of(event)
        if angle not in (0, 180) or getattr(event, 'quad_ref_deg', None) is None:
            return
        try:
            y = np.asarray(event.fitsub, dtype=float)
            f = np.asarray(event.scan.freq_list, dtype=float)
        except (AttributeError, TypeError, ValueError):
            return
        if len(y) == 0 or len(y) != len(f) or not np.any(y):
            return
        self._absorption = getattr(self, '_absorption', {})
        self._abs_count = getattr(self, '_abs_count', 0) + 1     # order of arrival (clocks tick too coarsely)
        self._absorption[angle] = (y if angle == 0 else -y, f[0], f[-1], getattr(event, 'quad_group', None),
                                   self._abs_count)

    def absorption_for(self, freqs):
        """The absorption for KK on this frequency grid, or None: the mean of the latest 0 deg and -1 x 180 deg
        records when both come from the same cycle, otherwise the more recent of the two. Cleared at each run
        start, so a baseline run's records are never used."""
        f = np.asarray(freqs, dtype=float)
        got = [v for v in getattr(self, '_absorption', {}).values()
               if len(v[0]) == len(f) and abs(v[1] - f[0]) < 1e-9 and abs(v[2] - f[-1]) < 1e-9]
        if not got:
            return None
        if len(got) == 2 and got[0][3] is not None and got[0][3] == got[1][3]:
            return np.mean([v[0] for v in got], axis=0)
        return max(got, key=lambda v: v[4])[0]

    def sub_method_for(self, event, jlab_sub):
        """MainWindow.end_event: the subtraction for this record. Dispersive (90/270 deg) records get the joint
        KK fit (dispersion.py) when an absorption on the same grid is known; everything else keeps JLab's."""
        d = self.cfg.get('dispersion') or {}
        if getattr(event, 'quad_ref_deg', None) not in (90, 270) or not d.get('joint_kk', True):
            return jlab_sub
        ref = self.absorption_for(event.scan.freq_list)
        if ref is None:
            event.quad_sub_method = 'wings (no 0 deg record yet)'
            return jlab_sub
        from .dispersion import make_sub
        return make_sub(jlab_sub, ref, int(d.get('order', 3)), int(d.get('edge', 3)), log)

    def save_session(self, saved):
        """MainWindow.save_session: phase_tune is always the Real tune; the other tunes get their own keys."""
        if self.sched.tunes[0] is not None:
            saved['phase_tune'] = float(self.sched.tunes[0])
        for angle, key in SESSION_KEYS.items():
            if self.sched.tunes.get(angle) is not None:
                saved[key] = float(self.sched.tunes[angle])

    # -- calibration ---------------------------------------------------------------
    def start_calibration(self):
        if self.calibrating():
            return
        if self.mw.run_in_progress() or self.mw.tune_tab.run_button.isChecked():
            self.message('Stop the Run and Tune loops before calibrating the phase.', logging.WARNING)
            return
        if not self.fpga:
            self.message('Phase calibration needs a DAQ with a phase DAC.', logging.WARNING)
            return
        from core.thread_manager import get_thread_manager
        from .calibration import CalibrationThread
        tunes = {a: v for a, v in self.sched.tunes.items() if v is not None}
        self.cal_thread = CalibrationThread(self.mw.config, self.cfg['cal'], tunes, self.mw.config.phase_vout,
                                            profile=getattr(self.mw, 'profile', None), out_dir=self.cal_dir)
        self.cal_thread.reply.connect(self.on_cal_reply)
        self.cal_thread.finished.connect(self.on_cal_finished)
        manager = get_thread_manager()
        manager.register_thread(self.cal_thread)
        self.mw.run_tab.run_button.setEnabled(False)
        self.mw.tune_tab.run_button.setEnabled(False)
        if self.ui:
            self.ui.cal_started()
        manager.start_thread(self.cal_thread.thread_name)
        self.message('Phase calibration running: stepping the phase DAC.')
        if self.ui:
            self.ui.refresh()

    # -- Auto Tune -------------------------------------------------------------------
    def start_autotune(self):
        """Tune-tab Auto Tune: refine the hand-set tunes the sequence uses to the true angles. Stops the Tune
        loop while it runs and starts it again afterwards."""
        if self.calibrating():
            return
        if self.mw.run_in_progress():
            self.message('Stop the Run loop before Auto Tune.', logging.WARNING)
            return
        if not self.fpga:
            self.message('Auto Tune needs a DAQ with a phase DAC.', logging.WARNING)
            return
        self.fill_opposites()
        angles = sorted(set(self.sched.sequence) | {0, 90})
        missing = [a for a in angles if self.sched.tunes.get(a) is None]
        same = [a for a in angles if a != 0 and a not in missing
                and abs(self.sched.tunes[a] - self.sched.tunes[0]) < 0.01]
        problem = None
        if missing:
            problem = f"set the {', '.join(ANGLE_LABELS.get(a, f'{a} deg') for a in missing)} tune by hand first"
        elif same:
            problem = (f"the {', '.join(ANGLE_LABELS.get(a, f'{a} deg') for a in same)} tune is at the Real tune; "
                       'set each tune roughly to its angle by hand first (within about 30 deg)')
        if problem:
            self.message(f'Auto Tune not started: {problem}.', logging.WARNING)
            if self.ui:
                self.ui.cal_label.setText(f'<span style="color:#d00000">Auto Tune not started: {problem}.</span>')
            return
        tune = self.mw.tune_tab
        self._resume_tune = tune.run_button.isChecked()
        if self._resume_tune:
            tune.run_button.setChecked(False)
            tune.run_pushed()                    # stops the tune loop; waits for its thread
        tunes = {a: float(self.sched.tunes[a]) for a in angles}
        self._autotune_undo = {a: self.sched.tunes.get(a) for a in angles}
        from core.thread_manager import get_thread_manager
        from .calibration import AutoTuneThread
        self.cal_thread = AutoTuneThread(self.mw.config, self.cfg['cal'], tunes, self.mw.config.phase_vout,
                                         self.cfg['autotune'], selected=self.selected,
                                         profile=getattr(self.mw, 'profile', None), out_dir=self.cal_dir)
        self.cal_thread.reply.connect(self.on_autotune_reply)
        self.cal_thread.finished.connect(self.on_cal_finished)
        manager = get_thread_manager()
        manager.register_thread(self.cal_thread)
        self.mw.run_tab.run_button.setEnabled(False)
        tune.run_button.setEnabled(False)
        if self.ui:
            self.ui.autotune_started()
        manager.start_thread(self.cal_thread.thread_name)
        self.message('Auto Tune running: stepping the phase DAC around ' +
                     ', '.join(ANGLE_LABELS.get(a, f'{a} deg') for a in angles) + '.')
        if self.ui:
            self.ui.refresh()

    def on_autotune_reply(self, data):
        name = 'polish pass' if data.get('polish') else f"pass {data.get('pass', 1)}"
        if 'step' in data:
            if self.ui:
                self.ui.cal_progress(data, what=f'Auto Tune {name}')
            return
        if data.get('stage') == 'fitting':
            if self.ui:
                self.ui.cal_label.setText(f"Auto Tune {name}: fitting {data['steps']} steps.")
            return
        rec = data.get('record')
        if rec is None:
            return
        res = rec.get('result')
        if rec.get('status') == 'ok' and res:
            new = {int(a): float(v) for a, v in res['tunes'].items()}
            for a, v in new.items():
                self.sched.tunes[a] = v
            if self.selected in new:
                self.mw.config.phase_vout = new[self.selected]   # the thread left the DAC there
            if self.ui:
                self.ui.show_selected_quietly()
        else:
            self._autotune_undo = None           # nothing was changed, so nothing to undo
        text = autotune_summary(rec)
        self.message(text + (f" Saved {data['path']}." if data.get('path') else ''),
                     logging.INFO if rec.get('status') == 'ok' else logging.WARNING)
        if self.ui:
            self.ui.show_autotune(rec, text)

    def undo_autotune(self):
        """Put back the tunes Auto Tune started from."""
        old = getattr(self, '_autotune_undo', None)
        if not old or self.calibrating() or self.mw.run_in_progress():
            return
        for a, v in old.items():
            self.sched.tunes[a] = v
        self._autotune_undo = None
        self.select_tune(self.selected)          # shows it and sends it to the box
        self.message('Auto Tune undone: tunes back to ' +
                     ', '.join(f"{ANGLE_LABELS.get(a, f'{a} deg')} at DAC {v * 100:.2f} %" for a, v in sorted(old.items())
                               if v is not None) + '.')

    def stop_calibration(self):
        if self.calibrating():
            self.cal_thread.stop_thread(timeout=30000)

    def on_cal_reply(self, data):
        if 'step' in data:
            if self.ui:
                self.ui.cal_progress(data)
            return
        if data.get('stage') == 'fitting':
            if self.ui:
                self.ui.cal_label.setText(f"Fitting {data['steps']} steps (a few seconds). Don't close PyNMR yet.")
            return
        rec = data.get('record')
        if rec is None:
            return
        path = data.get('path')
        if path is None:
            try:
                path = records.write_calibration(rec, self.cal_dir)
            except Exception as e:
                self.message(f'Could not write the calibration file: {e}', logging.ERROR)
        fit = rec.get('fit') or {}
        if fit.get('success'):
            self.sched.calibration = rec
        self.message(summary_line(rec) + (f' Saved {path}.' if path else ''),
                     logging.INFO if fit.get('success') else logging.WARNING)
        if self.ui:
            self.ui.show_calibration(rec)

    def on_cal_finished(self):
        self.mw.run_toggle()             # re-enables the Run and Tune buttons as JLab does after a run
        if getattr(self, '_resume_tune', False):
            self._resume_tune = False
            tune = self.mw.tune_tab
            tune.run_button.setChecked(True)
            tune.run_pushed()            # back to the tune loop Auto Tune interrupted
        if self.ui:
            self.ui.refresh()


def summary_line(rec):
    """One line describing a calibration result, for the status bar and log."""
    fit = rec.get('fit') or {}
    if not fit.get('success'):
        return f"Phase calibration {rec.get('status')}: {fit.get('message') or rec.get('error')}"
    clip = fit.get('clip_vout')
    parts = [f"Phase calibration {rec['cal_id']}: range {fit['range_deg']:.0f} deg"
             f"{'' if fit['monotonic'] else ' (not monotonic)'}"
             + (f", no change above {clip * 100:.0f} % DAC" if clip is not None else '')]
    for angle, t in sorted(fit['tunes'].items(), key=lambda kv: int(kv[0])):
        if angle == '0':
            continue
        err = f" +- {t['angle_err_deg']:.3f}" if t.get('angle_err_deg') is not None else ''
        parts.append(f"{angle} deg tune at {t['angle_deg']:.2f}{err} deg, gain {t['gain_ratio']:.4f}")
    parts.append(f"residual {fit['residual_rms_V'] * 1e3:.3f} mV")
    return '; '.join(parts) + '.'


ANGLE_LABELS = {0: 'Real', 90: 'Imag', 180: '180 deg', 270: '270 deg'}


def autotune_summary(rec):
    """One line describing an Auto Tune result, for the Tune tab, status bar and log."""
    res = rec.get('result')
    if rec.get('status') != 'ok' or not res:
        return f"Auto Tune {rec.get('status')}: {rec.get('error') or 'no result'}. Tunes unchanged."
    hand = rec.get('hand_tunes', {})
    parts = []
    for a, v in sorted(res['tunes'].items(), key=lambda kv: int(kv[0])):
        name = ANGLE_LABELS.get(int(a), f'{a} deg')
        off = res['hand_error_deg'].get(a)
        was = f', was {off:+.1f} deg off' if off is not None else ''
        g = res['gain_ratio'].get(a)
        gain = f', gain {g:.3f}' if (g is not None and int(a) != 0) else ''
        parts.append(f"{name} DAC {float(hand.get(a, v)) * 100:.2f} -> {v * 100:.2f} %{was}{gain}")
    steps = sum(len(p['steps']) for p in rec.get('passes', []))
    pol = res.get('polish') or {}
    if pol.get('used'):
        moved = max(abs(v) for v in pol['moved_deg'].values())
        polished = f' + polish, which moved them by at most {moved:.2f} deg'
    elif pol:
        polished = f" (polish not used: {pol.get('message')})"
    else:
        polished = ''
    zero = f" 0 deg: {res['zero_rule']}." if res.get('zero_rule') else ''
    warn = (f'<br><span style="color:#d00000">{res["zero_warning"]}.</span>' if res.get('zero_warning') else '')
    return (f"Auto Tune done ({res['passes']} pass{'es' if res['passes'] > 1 else ''}{polished}; {steps} steps): "
            + '; '.join(parts) + f". Absorptive direction at {res['ref_MHz']:.4f} MHz to "
            f"+-{res['theta_ref_err_deg']:.2f} deg; Q-curve arc {res['arc_deg']:.1f} deg across the window.{zero}"
            + warn)


def attach_quadrature(main_window):
    """Set up the quadrature feature if quadrature.yaml enables it for this profile. Never raises.

    Returns:
        the QuadController, or None
    """
    try:
        cfg = load_settings(getattr(main_window, 'profile', None))
        if not cfg['enable']:
            return None
        ctrl = QuadController(main_window, cfg)
        from .ui import QuadUI
        ctrl.ui = QuadUI(ctrl)
        bus = getattr(main_window, 'event_bus', None)
        if bus is not None:
            bus.subscribe(EventType.EVENT_FINISHED, ctrl.on_event_finished)
        main_window.quadrature = ctrl
        log.info('Quadrature controls attached (off until the Run-tab checkbox is ticked).')
        return ctrl
    except Exception as e:
        log.error(f'Quadrature not attached: {e}')
        return None
