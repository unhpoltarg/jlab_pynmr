"""Calibration step plan and fits, against the simulated Q-meter with known phase-DAC truth."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from unh.nmr_sim.qmeter import QMeter, QMeterParams
from unh.quadrature import calfit

F0 = 32.7
FREQ = np.linspace(F0 - 0.4, F0 + 0.4, 512)
CAL = {'v_min': 0.0, 'v_max': 0.94, 'steps': 41, 'passes': 2, 'ref_every': 5}
# SCPHS-51+ datasheet phase at 0..15 V, interpolated to 32.7 MHz; DAC fraction = V / 16
SCPHS_TABLE = tuple(zip(np.arange(16) / 16.0, [0.0, 15.4, 30.9, 48.4, 69.7, 96.7, 131.3, 177.8, 238.6, 306.4,
                                               367.8, 411.9, 441.1, 460.5, 473.6, 483.1]))
V_REAL, V_IMAG = 0.238, 0.4076


def run_plan(q, plan, noise_V=1.5e-3 / np.sqrt(128), seed=1):
    rng = np.random.default_rng(seed)
    vs, ts, sw = [], [], []
    for i, st in enumerate(plan):
        q.set_dac(st['vout'], 1)
        ph, _ = q.detect(q.voltage(FREQ))
        sw.append(ph + rng.normal(0, noise_V, ph.size))
        vs.append(st['vout'])
        ts.append(0.7 * i)
    return vs, ts, sw


def truth_angle(q, v):
    return q.phase_dac_deg(v) - q.phase_dac_deg(V_REAL)


def test_step_plan_has_refs_and_tunes():
    plan = calfit.step_plan(CAL, V_REAL, [V_IMAG])
    assert plan[0]['kind'] == 'ref' and plan[-1]['kind'] == 'ref'
    assert all(p['vout'] == V_REAL for p in plan if p['kind'] == 'ref')
    tune_steps = [p for p in plan if p['kind'] == 'tune']
    assert len(tune_steps) == 2 and all(abs(p['vout'] - V_IMAG) < 1e-9 for p in tune_steps)   # once per pass
    grid = [p['vout'] for p in plan if p['kind'] == 'grid']
    assert min(grid) == 0.0 and max(grid) == pytest.approx(0.94)
    passes = [p['pass'] for p in plan if p['kind'] != 'ref']
    assert passes == sorted(passes)                                    # pass 1 (up) then pass 2 (down)


def test_bin_sweep_averages():
    assert np.allclose(calfit.bin_sweep(np.arange(8.0), 4), [0.5, 2.5, 4.5, 6.5])


def test_datasheet_shaped_shifter_constant_gain_is_exact():
    """A strongly S-shaped phase map (no assumed shape in the fit) is recovered to far below 0.1 deg."""
    q = QMeter(QMeterParams(phase_dac_table=SCPHS_TABLE), F0)
    vs, ts, sw = run_plan(q, calfit.step_plan(CAL, V_REAL, [V_IMAG]))
    fit = calfit.fit_calibration(vs, ts, sw, V_REAL, tunes={0: V_REAL, 90: V_IMAG}, gain_order=2)
    assert fit['success'] and fit['monotonic']
    t = fit['tunes']['90']
    assert t['measured_step']
    assert t['angle_deg'] == pytest.approx(truth_angle(q, V_IMAG), abs=0.01)
    assert t['gain_ratio'] == pytest.approx(1.0, abs=1e-3)
    assert fit['range_deg'] == pytest.approx(483.1, abs=0.1)
    # the suggested 90 deg setting lands on the truth
    v90 = fit['suggested_vout']['90']
    assert truth_angle(q, v90) == pytest.approx(90.0, abs=0.05)


def test_linear_gain_and_offset_change_are_fitted():
    q = QMeter(QMeterParams(phase_dac_table=SCPHS_TABLE, phase_dac_gain_slope=-0.05, phase_dac_offset_V=0.05), F0)
    vs, ts, sw = run_plan(q, calfit.step_plan(CAL, V_REAL, [V_IMAG]))
    fit = calfit.fit_calibration(vs, ts, sw, V_REAL, tunes={0: V_REAL, 90: V_IMAG}, gain_order=1, offset_order=1)
    t = fit['tunes']['90']
    g_true = (1 - 0.05 * V_IMAG) / (1 - 0.05 * V_REAL)
    assert t['angle_deg'] == pytest.approx(truth_angle(q, V_IMAG), abs=0.01)
    assert t['gain_ratio'] == pytest.approx(g_true, abs=1e-4)
    assert fit['residual_rms_V'] < 3 * 1.5e-3 / np.sqrt(128 * 16)      # noise-limited (16 points per bin)


def test_linear_shifter_and_sign_convention():
    """A shifter whose phase falls with v is reported rising (the sign is not observable)."""
    q = QMeter(QMeterParams(phase_dac_curve_deg=(-200.0,)), F0)
    vs, ts, sw = run_plan(q, calfit.step_plan(CAL, V_REAL, [V_IMAG]))
    fit = calfit.fit_calibration(vs, ts, sw, V_REAL, tunes={0: V_REAL, 90: V_IMAG})
    assert fit['tunes']['90']['angle_deg'] == pytest.approx(abs(truth_angle(q, V_IMAG)), abs=0.01)
    assert np.all(np.diff(fit['phi_table']['phi_deg']) > 0)


def test_angle_and_gain_lookup_helpers():
    q = QMeter(QMeterParams(phase_dac_table=SCPHS_TABLE), F0)
    vs, ts, sw = run_plan(q, calfit.step_plan(CAL, V_REAL, [V_IMAG]))
    fit = calfit.fit_calibration(vs, ts, sw, V_REAL, tunes={0: V_REAL, 90: V_IMAG})
    assert calfit.angle_at(fit, V_REAL) == pytest.approx(0.0, abs=1e-9)
    assert calfit.angle_at(fit, V_IMAG) == pytest.approx(fit['tunes']['90']['angle_deg'])
    assert calfit.gain_at(fit, V_REAL) == pytest.approx(1.0)
    assert calfit.angle_at(None, 0.3) is None


def test_settle_fit_finds_tau_and_quiet_case():
    t = np.arange(1, 13) * 20.0
    y = 1.0 + 0.2 * np.exp(-(t - t[0]) / 30.0) + np.random.default_rng(0).normal(0, 1e-5, t.size)
    out = calfit.settle_fit(t, y)
    assert out['tau_ms'] == pytest.approx(30.0, rel=0.05)
    flat = calfit.settle_fit(t, 1.0 + np.random.default_rng(1).normal(0, 1e-5, t.size))
    assert flat['tau_ms'] is None and 'no transient' in flat['note']
