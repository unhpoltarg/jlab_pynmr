"""Quadrature feature: the hooks in MainWindow and the Run tab, event records, and a calibration run against
the simulator.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_quadrature.py
"""
import copy
import datetime
import io
import json
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import gc
from PySide6.QtCore import QCoreApplication

from config import Config
from core import Baseline, EventData
import gui.main_window as mw
from unh.quadrature import settings as qs
from unh.quadrature.controller import QuadController

V_REAL, V_IMAG = 0.238, 0.4076


@pytest.fixture(scope='module')
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


def channel():
    return {'name': 'Deuteron5T', 'species': 'deuteron', 'cent_freq': 32.7, 'mod_freq': 400.0,
            'power': 400.0, 'sweep_file': 'tri'}


def base_settings(tmp_path):
    return {'steps': 512, 'daq_type': 'FPGA', 'event_dir': str(tmp_path), 'tune_per_chunk': 32,
            'num_per_chunk': 64, 'compare_tab': {'enable': False}, 'ss_dir': ''}


class FakeDAQ:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def set_dac(self, v, c):
        self.calls.append((v, c))
        return self.ok


class FakeMain:
    """Stand-in for MainWindow with the methods the quadrature hooks touch."""
    replace_config = mw.MainWindow.replace_config
    set_event_base = mw.MainWindow.set_event_base
    epics_update = mw.MainWindow.epics_update
    end_finished = mw.MainWindow.end_finished

    def __init__(self, tmp_path):
        self.settings = base_settings(tmp_path)
        self.config = Config(channel(), self.settings)
        self.config.phase_vout = V_REAL
        self.service = None
        self.restore_dict = {'phase_tune_q': V_IMAG}
        self.messages = []
        self.status_bar = types.SimpleNamespace(showMessage=self.messages.append)
        self.sent = []
        self.tune_tab = types.SimpleNamespace(send_to_dac=lambda v, c: self.sent.append((v, c)),
                                              run_button=types.SimpleNamespace(isChecked=lambda: False))
        self.baseline = Baseline(self.config, {})
        self.event = types.SimpleNamespace()
        self.running = False
        self.profile = None

    def run_in_progress(self):
        return self.running


def controller(fake, **over):
    cfg = copy.deepcopy(qs.DEFAULTS)
    cfg['enable'] = True
    cfg.update(over)
    fake.quadrature = QuadController(fake, cfg)     # as attach_quadrature does
    # the short Tune-style connection used before the first event of a run: record instead of connecting
    fake.prewrites, fake.prewrite_ok = [], True
    fake.quadrature._write_now = lambda v: fake.prewrites.append(v) or fake.prewrite_ok
    return fake.quadrature


def one_event(ctrl, fake, daq=None, completed=True):
    """What RunTab.start_thread and RunThread do for one event, minus the sweeps themselves."""
    a = ctrl.before_event()
    event = types.SimpleNamespace(config=fake.config)
    fake.event = event
    fake.set_event_base()
    ctrl.tag_event(event)
    ctrl.after_sweeps(daq if daq is not None else FakeDAQ(), completed)
    return a, event


def test_tunes_restored_from_session(tmp_path):
    ctrl = controller(FakeMain(tmp_path))
    assert ctrl.sched.tunes[0] == V_REAL and ctrl.sched.tunes[90] == V_IMAG


def test_checkbox_off_changes_nothing(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    config0 = fake.config
    daq = FakeDAQ()
    a, event = one_event(ctrl, fake, daq)
    assert fake.config is config0 and daq.calls == []
    assert not any(k.startswith('quad_') for k in vars(event))


def test_alternation_builds_new_configs_and_writes_each_tune(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    assert ctrl.set_active(True)
    configs, angles, writes, sets = [], [], [], []
    for _ in range(4):
        daq = FakeDAQ()
        a, event = one_event(ctrl, fake, daq)
        configs.append(fake.config)
        angles.append(event.quad_ref_deg)
        writes.append(daq.calls)
        sets.append(event.quad_dac_set)
        assert event.config.phase_vout == a.vout and event.quad_vout == a.vout and event.quad_dac_ok is True
    assert angles == [0, 90, 0, 90]
    assert [c.phase_vout for c in configs] == [V_REAL, V_IMAG, V_REAL, V_IMAG]   # each Config kept its value
    assert len({id(c) for c in configs}) == 4                                  # never edited in place
    # the first event's tune comes from a short Tune-style connection; nothing is written while an event is set up
    assert fake.prewrites == [V_REAL]
    # each event, once its sweeps are in, puts the NEXT event's tune on the box with the Tune latch sequence
    assert writes == [[(V_IMAG, 0), (V_IMAG, 1)], [(V_REAL, 0), (V_REAL, 1)],
                      [(V_IMAG, 0), (V_IMAG, 1)], [(V_REAL, 0), (V_REAL, 1)]]
    assert sets[0].startswith('before the event') and set(sets[1:]) == {'end of previous event'}
    ctrl.run_finished()
    assert fake.config.phase_vout == V_REAL and fake.sent == []               # box already back on Real


def test_failed_event_makes_the_next_one_write_first(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.set_active(True)
    one_event(ctrl, fake)                                   # 0 deg; afterwards the box holds the 90 deg tune
    daq = FakeDAQ()
    a, event = one_event(ctrl, fake, daq, completed=False)   # 90 deg event fails: nothing written after it
    assert event.quad_dac_set == 'end of previous event' and daq.calls == [] and ctrl.sched._dac_vout is None
    a, event = one_event(ctrl, fake)                        # next (0 deg) writes its tune before starting
    assert fake.prewrites == [V_REAL, V_REAL] and event.quad_dac_set.startswith('before the event')
    ctrl.run_finished()                                     # box was left on the 90 deg tune: put back on Real
    assert fake.sent == [(V_REAL, 1)]


def test_end_of_event_refusal_suspends(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.set_active(True)
    one_event(ctrl, fake, FakeDAQ(ok=False))                # writing the 90 deg tune after the sweeps fails
    assert ctrl.sched.suspended
    a, event = one_event(ctrl, fake)
    assert event.quad_ref_deg == 0 and event.quad_state == 'suspended' and fake.config.phase_vout == V_REAL


def test_refuses_without_imag_tune(tmp_path):
    fake = FakeMain(tmp_path)
    fake.restore_dict = {}
    ctrl = controller(fake)
    assert not ctrl.set_active(True)
    assert 'Imag' in fake.messages[-1]


def test_box_refusal_suspends_quadrature(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.set_active(True)
    fake.prewrite_ok = False                                # the box refuses the first event's tune
    a, event = one_event(ctrl, fake)
    assert event.quad_dac_ok is False and ctrl.sched.suspended
    fake.prewrite_ok = True
    a, event = one_event(ctrl, fake)
    assert event.quad_ref_deg == 0 and event.quad_state == 'suspended' and fake.config.phase_vout == V_REAL


def test_baseline_per_angle_with_fallback(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.set_active(True)
    stop = datetime.datetime(2026, 10, 27, 12, 0)
    ctrl.new_baselines({90: {'phase': np.full(512, 9.0), 'stop_stamp': 90.0, 'stop_time': stop, 'base_file': 'f90',
                             'quad_ref_deg': 90}})
    a, e0 = one_event(ctrl, fake)                    # 0 deg: no 0 deg baseline, so the main one
    assert e0.base_stamp == fake.baseline.stop_stamp and e0.quad_base_ref_deg is None
    a, e90 = one_event(ctrl, fake)
    assert e90.base_stamp == 90.0 and np.all(e90.baseline == 9.0) and e90.quad_base_ref_deg == 90


def test_epics_written_only_for_real_records(tmp_path):
    fake = FakeMain(tmp_path)
    writes, reads = [], []
    fake.epics = types.SimpleNamespace(write_event=writes.append, read_all=lambda: reads.append(1), read_pvs={})
    plain, real, imag = (types.SimpleNamespace(), types.SimpleNamespace(quad_ref_deg=0),
                         types.SimpleNamespace(quad_ref_deg=90))
    for e in (plain, real, imag):
        fake.epics_update(e)
    assert writes == [plain, real] and len(reads) == 3 and imag.epics == {}


def test_history_only_for_real_records(tmp_path):
    fake = FakeMain(tmp_path)
    added = []
    fake.eventfile, fake.eventfile_lines = io.StringIO(), 0
    fake.history = types.SimpleNamespace(add_hist=lambda point, f: added.append(point))
    fake.hist_file = io.StringIO()
    fake.run_tab = fake.te_tab = types.SimpleNamespace(update_event_plots=lambda: None)
    fake.start_end = datetime.datetime.now(tz=datetime.timezone.utc)
    fake.start_pending_run = lambda: None
    fake.event = types.SimpleNamespace(stop_time=fake.start_end)
    monkey = []
    for angle in (None, 90, 0):
        ev = types.SimpleNamespace(print_event=lambda f: f.write('{}\n'), elapsed=1)
        if angle is not None:
            ev.quad_ref_deg = angle
        fake.previous_event = ev
        original = mw.HistPoint
        mw.HistPoint = lambda e: e
        try:
            fake.end_finished()
        finally:
            mw.HistPoint = original
        monkey.append(ev)
    assert added == [monkey[0], monkey[2]]
    assert fake.eventfile.getvalue().count('\n') == 3          # every record is still written


def test_event_record_fields(tmp_path):
    """A real EventData: quad fields appear only when tagged, as plain top-level JSON values."""
    fake = FakeMain(tmp_path)
    parent = types.SimpleNamespace(config=fake.config, chassis_temp=0, shimA=0, shimB=0, shimC=0, shimD=0)
    out = io.StringIO()
    EventData(parent).print_event(out)
    plain = json.loads(out.getvalue())
    assert not any(k.startswith('quad_') for k in plain)

    ctrl = controller(fake)
    ctrl.set_active(True)
    ctrl.before_event()
    ctrl.before_event()                              # second event: Imag
    parent.config = fake.config
    event = EventData(parent)
    ctrl.tag_event(event)
    event.quad_base_ref_deg = None
    out = io.StringIO()
    event.print_event(out)
    rec = json.loads(out.getvalue())
    assert set(plain) <= set(rec)
    assert rec['phase_vout'] == V_IMAG and rec['quad_ref_deg'] == 90 and rec['quad_vout'] == V_IMAG
    assert rec['quad_mode'] == 'pair' and rec['quad_index'] == 1 and rec['label'] == 'None'


def test_session_keeps_real_in_phase_tune(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    fake.config.phase_vout = V_IMAG                   # Tune tab left on Imag
    saved = {'phase_tune': fake.config.phase_vout}
    ctrl.save_session(saved)
    assert saved == {'phase_tune': V_REAL, 'phase_tune_q': V_IMAG}


def test_streamer_skips_non_real(qapp):
    from unh import data_streamer as ds
    s = ds.DataStreamer(dict(ds.DEFAULTS))
    event = types.SimpleNamespace(config=types.SimpleNamespace(channel=channel()))
    assert s.wants(event)
    event.quad_ref_deg = 90
    assert not s.wants(event)


def test_attach_is_off_by_default(tmp_path, monkeypatch):
    from unh.quadrature import controller as qc
    fake = FakeMain(tmp_path)
    monkeypatch.setattr(qc, 'load_settings', lambda profile=None: copy.deepcopy(qs.DEFAULTS))
    assert qc.attach_quadrature(fake) is None and not hasattr(fake, 'quadrature')


# -- calibration against the simulator -------------------------------------------------------------------

SCPHS_TABLE = [[v / 16.0, d] for v, d in enumerate([0.0, 15.4, 30.9, 48.4, 69.7, 96.7, 131.3, 177.8, 238.6, 306.4,
                                                    367.8, 411.9, 441.1, 460.5, 473.6, 483.1])]


@pytest.fixture
def sim_config(tmp_path):
    from unh.nmr_sim import simulator as simmod
    simmod.reset_simulator()
    settings = base_settings(tmp_path)
    settings.update({'daq_type': 'Test', 'test_source': 'sim', 'fpga_settings': {'timeout_tune': 1},
                     'nmr_sim': {'seed': 7, 'sweep_time_s': 0.0, 'truth_log_dir': None,
                                 'qmeter': {'phase_dac_table': SCPHS_TABLE, 'ref_phase_offset_deg': -65.7,
                                            'phase_dac_gain_slope': -0.02, 'phase_dac_offset_V': 0.01}}})
    config = Config(channel(), settings)
    config.phase_vout = V_REAL
    yield config
    simmod.reset_simulator()


def test_calibration_thread_against_simulator(qapp, sim_config, tmp_path):
    from unh.nmr_sim import simulator as simmod
    from unh.quadrature.calibration import CalibrationThread
    cal = dict(qs.DEFAULTS['cal'], steps=21, sweeps_per_step=64, gain_order=1, settle_test_chunks=6)
    replies = []
    t = CalibrationThread(sim_config, cal, {0: V_REAL, 90: V_IMAG}, restore_vout=V_REAL, out_dir=str(tmp_path / 'qc'))
    t.reply.connect(replies.append)
    t.setup()
    t.execute()
    t.cleanup()
    rec = t.record
    assert rec['status'] == 'ok' and rec['record_type'] == 'quad_calibration'
    assert rec['sweeps_per_step'] == 64 and all(s['num'] == 64 and s['dac_ok'] for s in rec['steps'])
    assert len(rec['steps']) == len([r for r in replies if 'step' in r])
    assert replies[-1]['done'] and rec['settle_test']['tau_ms'] is None     # the simulated shifter is instant
    q = simmod._SIM.qmeter                                                   # the simulator the thread used
    truth = q.phase_dac_deg(V_IMAG) - q.phase_dac_deg(V_REAL)
    fit = rec['fit']
    assert fit['success'] and fit['tunes']['90']['angle_deg'] == pytest.approx(truth, abs=0.05)
    assert fit['tunes']['90']['gain_ratio'] == pytest.approx((1 - 0.02 * V_IMAG) / (1 - 0.02 * V_REAL), abs=1e-3)
    assert q._phase_target == V_REAL                                         # DAC left on the restore value
    t.reply.disconnect()
    del t
    gc.collect()                     # free the QThread while Qt is alive (BaseThread.__del__ crashes at exit)
    json.dumps(rec)
    saved = json.load(open(replies[-1]['path']))                              # written by the thread itself
    assert saved['status'] == 'ok' and saved['fit']['success'] and len(saved['steps']) == len(rec['steps'])
    assert any(r.get('stage') == 'fitting' for r in replies)

def test_calibration_stop_skips_fit_and_saves(qapp, sim_config, tmp_path):
    """A stop (e.g. closing PyNMR) must finish fast: no fit, steps saved, DAC restored."""
    from unh.nmr_sim import simulator as simmod
    from unh.quadrature.calibration import CalibrationThread
    cal = dict(qs.DEFAULTS['cal'], steps=21, sweeps_per_step=32, settle_test_chunks=4)
    t = CalibrationThread(sim_config, cal, {0: V_REAL, 90: V_IMAG}, restore_vout=V_REAL, out_dir=str(tmp_path / 'qc'))
    replies = []
    t.reply.connect(replies.append)
    t.reply.connect(lambda d: setattr(t, '_is_stopping', d.get('step') == 5 or t._is_stopping))
    t.setup()
    t.execute()
    t.cleanup()
    rec = json.load(open(replies[-1]['path']))
    assert rec['status'] == 'stopped' and len(rec['steps']) == 5 and not rec['fit']['success']
    assert not any(r.get('stage') == 'fitting' for r in replies)
    assert simmod._SIM.qmeter._phase_target == V_REAL
    t.reply.disconnect()
    del t
    gc.collect()

def test_cycle4_fills_opposite_tunes_from_calibration(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.sched.tunes[0], ctrl.sched.tunes[90] = 0.4, 0.625          # phi = 400 (v - 0.4): Imag at +90 deg
    v = np.linspace(0, 1, 21)
    ctrl.sched.calibration = {'cal_id': 'C', 'channel': 'Deuteron5T', 'tunes': {'0': 0.4, '90': 0.625},
                              'fit': {'success': True, 'v_real': 0.4, 'gain_coeffs': [], 'clip_vout': None,
                                      'phi_table': {'vout': v.tolist(), 'phi_deg': (400 * (v - 0.4)).tolist()}}}
    ctrl.set_sequence(qs.SEQUENCES['cycle4'])
    assert ctrl.set_active(True)
    assert ctrl.sched.tunes[180] == pytest.approx(0.85, abs=1e-3)   # Real + 180 deg (Real - 180 is out of range)
    assert ctrl.sched.tunes[270] == pytest.approx(0.175, abs=1e-3)  # Imag - 180 deg (Imag + 180 is out of range)


# --- Auto Tune -------------------------------------------------------------------------------------------

def _abs_error_deg(q, v, offset_deg, nominal):
    """How far DAC value v puts the simulated reference from ``nominal`` deg past absorptive (mod 180 for 0/180)."""
    e = q.phase_dac_deg(v) + offset_deg - nominal
    return (e + 90.0) % 180.0 - 90.0


def test_fit_trace_normal_is_the_absorption_direction():
    from unh.nmr_sim.qmeter import QMeter, QMeterParams
    from unh.quadrature import autotune
    rng = np.random.default_rng(3)
    circuits = [{}, {'R_cc_ohm': 50.0, 'R_damp_ohm': 16.7, 'cable_half_waves': 0, 'L0_uH': 2.15}]
    for kw in circuits:
        for detune in (0.0, 0.1):
            q = QMeter(QMeterParams(tune_MHz=32.7 + detune, **kw), 32.7)
            f = np.linspace(32.5, 32.9, 32)
            frame = q.phi_abs + np.radians(37.0)
            W = q.G_phase * q.voltage(f) * np.exp(-1j * frame)
            W += 0.3e-3 * (rng.standard_normal(32) + 1j * rng.standard_normal(32))
            t = autotune.fit_trace(f, W)
            dV = q.voltage(32.7, -1j * 1e-9) - q.voltage(32.7, 0.0)       # absorption at the centre frequency
            truth = np.degrees(np.angle(dV) - frame)
            err = (t['theta_ref_deg'] - truth + 90.0) % 180.0 - 90.0
            assert t['success'] and abs(err) < 0.5, (kw, detune, err)


def test_target_angles_follow_the_hand_tunes():
    from unh.quadrature.autotune import target_angles
    t = target_angles(10.0, {0: 0.0, 90: -80.0, 180: 185.0, 270: 95.0})
    assert t[0] == pytest.approx(10.0) and t[180] == pytest.approx(190.0)
    assert t[90] == pytest.approx(-80.0) and t[270] == pytest.approx(100.0)
    t = target_angles(170.0, {0: 0.0, 90: 100.0})          # 0/180 and +-90 are picked nearest the hand tunes
    assert t[0] == pytest.approx(-10.0) and t[90] == pytest.approx(80.0)


def test_autotune_thread_finds_true_angles(qapp, sim_config, tmp_path):
    from unh.nmr_sim import simulator as simmod
    from unh.quadrature.calibration import AutoTuneThread
    at = dict(copy.deepcopy(qs.DEFAULTS['autotune']), map=False)   # the hand-tune method
    hand = {0: V_REAL + 0.02, 90: V_IMAG - 0.015}                       # about 7 and 11 deg off
    t = AutoTuneThread(sim_config, qs.DEFAULTS['cal'], hand, restore_vout=hand[0], at=at, selected=90,
                       out_dir=str(tmp_path / 'qc'))
    replies = []
    t.reply.connect(replies.append)
    t.setup()
    t.execute()
    t.cleanup()
    rec = t.record
    assert rec['status'] == 'ok', rec['error']
    assert rec['result']['polish']['used'] and rec['passes'][-1]['kind'] == 'polish'
    assert rec['passes'][-1]['offsets'] == at['polish_offsets']
    q = simmod._SIM.qmeter
    new = {int(a): v for a, v in rec['result']['tunes'].items()}
    assert abs(_abs_error_deg(q, new[0], -65.7, 0)) < 0.5
    assert abs(_abs_error_deg(q, new[90], -65.7, 90)) < 0.5
    assert rec['result']['hand_error_deg']['0'] == pytest.approx(_abs_error_deg(q, hand[0], -65.7, 0), abs=1.0)
    assert q._phase_target == pytest.approx(new[90])                    # left on the selected (Imag) tune
    assert replies[-1]['autotune_done'] and json.load(open(replies[-1]['path']))['record_type'] == 'quad_autotune'
    from unh.quadrature import records
    assert records.latest_calibration(str(tmp_path / 'qc')) is None     # never mistaken for a calibration
    t.reply.disconnect()
    del t
    gc.collect()


# --- Dispersive records ------------------------------------------------------------------------------------

def _line(f, f0=32.7, w=0.03, split=0.06):
    """A two-horn absorption and its dispersion (sum of Lorentzians: chi'' and chi')."""
    a = d = 0.0
    for c in (f0 - split, f0 + split):
        u = (f - c) / w
        a = a + 1.0 / (1 + u ** 2)
        d = d + u / (1 + u ** 2)
    return a, d


def test_joint_kk_keeps_the_dispersion_tails():
    from unh.quadrature import dispersion
    f = np.linspace(32.5, 32.9, 512)
    a, d = _line(f)
    x = (f - 32.7) / 0.2
    background = 0.5 + 0.3 * x - 0.2 * x ** 2 + 0.1 * x ** 3
    rng = np.random.default_rng(5)
    y = background + 0.8 * d + 0.002 * rng.standard_normal(len(f))
    bg, kk, s = dispersion.joint_kk_fit(f, y, a + 0.002 * rng.standard_normal(len(f)))
    sub = y - bg
    core = slice(3, -3)
    assert abs(abs(s) - 0.8) < 0.08                          # the KK scale (sign is a convention)
    assert np.sqrt(np.mean((sub - 0.8 * d)[core] ** 2)) < 0.03    # the dispersion, tails included
    wings = (np.arange(len(f)) < 0.25 * len(f)) | (np.arange(len(f)) > 0.75 * len(f))
    p = np.polyfit(x[wings], y[wings], 3)                     # what a cubic wing fit leaves
    wing_sub = y - np.polyval(p, x)
    assert np.sqrt(np.mean((wing_sub - 0.8 * d)[core] ** 2)) > 3 * np.sqrt(np.mean((sub - 0.8 * d)[core] ** 2))


def test_dispersive_records_get_the_joint_fit(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    f = np.linspace(32.5, 32.9, 256)
    a, d = _line(f)
    jlab = lambda ev: ('jlab', 'jlab')
    ev = lambda angle, **kw: types.SimpleNamespace(quad_ref_deg=angle, scan=types.SimpleNamespace(freq_list=f), **kw)
    e90 = ev(90, basesub=0.2 + d)
    assert ctrl.sub_method_for(e90, jlab) is jlab and e90.quad_sub_method.startswith('wings (no 0 deg')
    ctrl._keep_absorption(ev(180, fitsub=np.full(len(f), 1e-6), quad_group='baseline run'))
    ctrl._keep_absorption(ev(0, fitsub=a, quad_group='g1'))
    assert np.allclose(ctrl.absorption_for(f), a)               # another cycle's 180 deg is not mixed in
    ctrl._keep_absorption(ev(180, fitsub=-3 * a, quad_group='g1'))
    assert np.allclose(ctrl.absorption_for(f), 2 * a)           # same cycle: mean of 0 and -1 x 180
    ctrl._keep_absorption(ev(180, fitsub=-a, quad_group='g1'))
    assert np.allclose(ctrl.absorption_for(f), a)
    assert ctrl.sub_method_for(ev(0, basesub=a), jlab) is jlab                 # absorptive records keep JLab's
    fitcurve, fitsub = ctrl.sub_method_for(e90, jlab)(e90)
    assert e90.quad_sub_method == 'joint KK' and np.allclose(fitcurve + fitsub, e90.basesub)
    # the line's own dispersion stays in Fit Subtracted; only a smooth part (the KK of absorption outside the
    # window, which no in-window transform can know) goes into the background with the 0.2 offset
    assert np.sqrt(np.mean((fitsub - d)[3:-3] ** 2)) < 0.05 and len(e90.quad_kk_curve) == len(f)
    assert ctrl.absorption_for(np.linspace(32.0, 33.0, 64)) is None            # another window: no reference


def test_frown_rule_picks_the_absorptive_side_opposite_the_diode():
    from unh.quadrature import autotune
    f = np.linspace(32.3, 33.1, 32)
    x = (f - 32.7) / 0.4
    W = (1.0 + 0.3 * x ** 2) + 1j * (0.8 * x)       # absorptive along +real with a smile, dispersive along +imag
    smile = (0.2, 0.001)
    frown = (-0.2, 0.001)
    assert autotune.frown_zero(f, W, 0.0, smile)[0] == pytest.approx(180.0)   # diode smile -> phase frown
    assert autotune.frown_zero(f, W, 0.0, frown)[0] == pytest.approx(0.0)
    assert autotune.frown_zero(f, W, 0.0, (1e-5, 1e-3))[0] is None             # can't tell: the hand tune decides


def test_autotune_cycle4_swaps_real_and_180_to_follow_the_frown_rule(qapp, sim_config, tmp_path):
    from unh.nmr_sim import simulator as simmod
    from unh.quadrature import autotune
    from unh.quadrature.calibration import AutoTuneThread
    hand = {0: 0.245, 90: 0.40, 180: 0.515, 270: 0.59}     # Real by hand on the side that curves like the diode
    t = AutoTuneThread(sim_config, qs.DEFAULTS['cal'], hand, restore_vout=hand[0],
                       at=dict(copy.deepcopy(qs.DEFAULTS['autotune']), map=False), selected=0,
                       out_dir=str(tmp_path / 'qc'))
    t.setup()
    t.execute()
    t.cleanup()
    rec = t.record
    assert rec['status'] == 'ok', rec['error']
    new = {int(a): v for a, v in rec['result']['tunes'].items()}
    q = simmod._SIM.qmeter
    f = np.linspace(32.3, 33.1, 512)
    q.set_dac(new[0], 1)
    ph, di = q.detect(q.voltage(f))
    assert np.sign(autotune.wing_curvature(f, ph)) != np.sign(autotune.wing_curvature(f, di))
    assert abs(new[0] - hand[180]) < 0.03 and abs(new[180] - hand[0]) < 0.03   # Real and 180 swapped sides
    assert not rec['result'].get('zero_warning')
    t.reply.disconnect()
    del t
    gc.collect()


def test_signal_area_has_a_line_per_angle_updated_only_by_its_own_records(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    ctrl.sched.sequence = [0, 90, 180, 270]
    ctrl.sched.active = True
    shown = {}
    fake.run_tab = types.SimpleNamespace(
        area_value=types.SimpleNamespace(setText=lambda t: shown.__setitem__('area', t)),
        pol_value=types.SimpleNamespace(setText=lambda t: shown.__setitem__('pol', t)))
    rec = lambda angle, area: types.SimpleNamespace(quad_ref_deg=angle, area=area, pol=0.1,
                                                    scan=types.SimpleNamespace(freq_list=np.zeros(3), phase=np.zeros(3)),
                                                    fitsub=np.zeros(3))
    ctrl.on_event_finished({'event': rec(0, 1.5)})
    assert '0\u00b0: 1.500000' in shown['area'] and '90\u00b0: waiting' in shown['area']
    ctrl.on_event_finished({'event': rec(90, 0.25)})
    ctrl.on_event_finished({'event': rec(180, -1.4)})
    assert '0\u00b0: 1.500000' in shown['area'] and '90\u00b0: 0.250000' in shown['area']
    assert '180\u00b0: -1.400000' in shown['area'] and '270\u00b0: waiting' in shown['area']
    ctrl.on_event_finished({'event': rec(0, 1.6)})
    assert '0\u00b0: 1.600000' in shown['area'] and '90\u00b0: 0.250000' in shown['area']


# --- Auto Tune with a coarse map first (autotune: map: True) ----------------------------------------------------

def _true_deg(q, v):
    """Simulated reference phase of DAC value v, deg past the simulator's absorptive 0, in (-180, 180]."""
    return (q.phase_dac_deg(v) - 65.7 + 180.0) % 360.0 - 180.0


def _mapped_autotune(sim_config, tmp_path, hand, side90=None):
    from unh.quadrature.calibration import AutoTuneThread
    t = AutoTuneThread(sim_config, qs.DEFAULTS['cal'], hand, restore_vout=hand[0],
                       at=copy.deepcopy(qs.DEFAULTS['autotune']), selected=0, out_dir=str(tmp_path / 'qc'),
                       side90=side90, angles=[0, 90, 180, 270])
    t.setup()
    t.execute()
    t.cleanup()
    rec = t.record
    del t
    gc.collect()
    return rec


def test_mapped_autotune_finds_every_tune_and_the_most_equal_gains(qapp, sim_config, tmp_path):
    """From rough Real and Imag tunes only, the map finds all four; 180 deg can be reached at two settings, and the
    one that makes the four gains most equal is kept. The 90 deg side is then kept even if the hand Imag tune moves."""
    from unh.nmr_sim import simulator as simmod
    from unh.quadrature import autotune
    sim_config.settings['nmr_sim']['qmeter']['phase_dac_gain_slope'] = -0.2     # gain falls 20 % across the DAC
    simmod.reset_simulator()
    rec = _mapped_autotune(sim_config, tmp_path, {0: V_REAL + 0.02, 90: V_IMAG - 0.015})
    assert rec['status'] == 'ok', rec['error']
    res = rec['result']
    assert [p['kind'] for p in rec['passes']] == ['map', 'candidates', 'polish'] and res['mapped']
    q = simmod._SIM.qmeter
    new = {int(a): v for a, v in res['tunes'].items()}
    # this circuit's diode is a frown, so the frown rule puts 0 deg on the simulator's 180 (as the cycle4 test does)
    assert abs(_true_deg(q, new[0]) - 180.0) % 360.0 < 0.5 or abs(_true_deg(q, new[0]) + 180.0) < 0.5
    assert abs(_true_deg(q, new[180])) < 0.5
    assert abs(_true_deg(q, new[90]) - 90.0) < 0.5 and abs(_true_deg(q, new[270]) + 90.0) < 0.5   # hand Imag side
    opts = res['choices']['180']
    assert len(opts) == 2                                  # 180 deg two ways: about 23.8 % and 71.7 % DAC
    true_gain = lambda v: 1.0 - 0.2 * v
    def spread(v180):
        g = [true_gain(new[0]), true_gain(new[90]), true_gain(v180), true_gain(new[270])]
        return max(g) / min(g)
    best = min((o['vout'] for o in opts), key=spread)
    assert new[180] == pytest.approx(best, abs=0.01)       # the most equal gains (here the 71.7 % setting)
    for a, g in res['gain_ratio'].items():                 # gains measured as the simulator has them
        assert g == pytest.approx(true_gain(new[int(a)]) / true_gain(new[0]), abs=0.003)
    assert res['side90_source'] == 'from the hand Imag tune'
    from unh.quadrature.controller import autotune_summary
    assert 'kept' in autotune_summary(rec) and '180 deg found at' in autotune_summary(rec)
    # second run: the hand Imag tune now sits on the other dispersive side; the kept side wins
    simmod.reset_simulator()
    rec2 = _mapped_autotune(sim_config, tmp_path, {0: V_REAL, 90: 0.5922}, side90=res['side90'])
    assert rec2['status'] == 'ok', rec2['error']
    new2 = {int(a): v for a, v in rec2['result']['tunes'].items()}
    assert abs(_true_deg(simmod._SIM.qmeter, new2[90]) - 90.0) < 0.5
    assert rec2['result']['side90_source'] == 'kept from the last Auto Tune'


def test_candidates_and_the_choice_rule():
    from unh.quadrature import autotune
    lev = np.linspace(0.0, 0.9, 10)
    phi = np.linspace(-60.0, 420.0, 10)                    # 480 deg: 0 deg (mod 360) is reached twice
    c = autotune.candidates_for(lev, phi, 0.0, 0.0, 0.9)
    assert len(c) == 2 and c[0] == pytest.approx(60 / 480 * 0.9, abs=1e-4) and c[1] == pytest.approx(0.7875, abs=1e-4)
    assert autotune.candidates_for(lev, phi, 0.0, 0.0, 0.5) == [c[0]]       # the second is above the usable top
    assert len(autotune.candidates_for(lev, phi, 180.0, 0.0, 0.9)) == 1
    pick, spread = autotune.choose_combination({0: {0.2: 1.00}, 180: {0.3: 0.957, 0.7: 0.970}})
    assert pick == {0: 0.2, 180: 0.7} and spread == pytest.approx(1 / 0.970 - 1)
    # within the tie margin the larger signal wins
    pick, _ = autotune.choose_combination({0: {0.2: 1.00}, 180: {0.3: 0.999, 0.7: 1.0015}}, tie=0.003)
    assert pick[180] == 0.7
    pick, _ = autotune.choose_combination({0: {0.2: 1.00, 0.8: 1.10}, 90: {0.5: 1.05}})
    assert pick == {0: 0.8, 90: 0.5} or pick == {0: 0.2, 90: 0.5}         # both 5 % apart: the larger mean
    assert pick == {0: 0.8, 90: 0.5}
    assert autotune.side_from_hand(80.0, 0.0) == 1 and autotune.side_from_hand(-100.0, 0.0) == -1


def test_side90_is_saved_with_the_session(tmp_path):
    fake = FakeMain(tmp_path)
    ctrl = controller(fake)
    assert ctrl.side90 is None
    ctrl.side90 = -1
    saved = {}
    ctrl.save_session(saved)
    assert saved['quad_side90'] == -1
    fake.restore_dict = dict(fake.restore_dict, quad_side90=-1)
    assert controller(fake).side90 == -1
