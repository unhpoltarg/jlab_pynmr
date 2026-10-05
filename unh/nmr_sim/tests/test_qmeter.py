"""Q-meter: transmission-line limits, tuning, ideal-circuit shapes, chi linearity, DACs."""

import numpy as np
import pytest

from unh.nmr_sim.qmeter import (C_M_PER_S, QMeter, QMeterParams, cable_input_impedance,
                            coil_impedance, omega)

F0 = 32.7


def _ideal(**kw):
    """Ideal current drive, open detector, no cable."""
    p = dict(U_V=1e12 * 1e-3, R_cc_ohm=1e12, Z_amp_ohm=None, cable_half_waves=0,
             L0_uH=0.5, r_coil_ohm=0.3, R_damp_ohm=1.0)
    p.update(kw)
    return QMeter(QMeterParams(**p), F0)


def test_half_wave_line_is_transparent():
    Z_L = coil_impedance(F0, 0.5e-6, 0.3)
    v_f = 0.66
    half = v_f * C_M_PER_S / (2 * F0 * 1e6)
    Z_in = cable_input_impedance(Z_L, F0, 50.0, half, v_f, 0.0)
    assert abs(Z_in - Z_L) / abs(Z_L) < 1e-9


def test_quarter_wave_line_inverts():
    Z_L = coil_impedance(F0, 0.5e-6, 0.3)
    v_f = 0.66
    quarter = v_f * C_M_PER_S / (4 * F0 * 1e6)
    Z_in = cable_input_impedance(Z_L, F0, 50.0, quarter, v_f, 0.0)
    assert abs(Z_in - 50.0 ** 2 / Z_L) / abs(Z_in) < 1e-9


@pytest.mark.parametrize("params", [QMeterParams(), QMeterParams(L0_uH=0.5, R_damp_ohm=1.0)])
def test_autotune_resonant(params):
    q = QMeter(params, F0)
    assert abs(np.imag(q.tank(F0))) < 1e-9 * abs(q.tank(F0))


def test_ideal_phase_flat_and_diode_width():
    q = _ideal()
    f = np.linspace(F0 - 1.5, F0 + 1.5, 300001)
    ph, di = q.detect(q.voltage(f))
    assert np.ptp(ph) < 1e-9 * abs(np.mean(ph))
    # |Z_T| = sqrt(2) R at X = +-R; separation ~ f0/Q for a series LCR
    mag = np.abs(di / di[np.argmin(np.abs(f - F0))])
    lo = f[(f < F0) & (mag >= np.sqrt(2))].max()
    hi = f[(f > F0) & (mag >= np.sqrt(2))].min()
    assert (hi - lo) == pytest.approx(F0 / q.loaded_Q(), rel=1e-3)


def _gauss(f):
    return np.exp(-0.5 * ((f - F0) / 0.05) ** 2)


def test_ideal_small_chi_absorption_is_linear():
    q = _ideal()
    f = np.linspace(F0 - 0.4, F0 + 0.4, 512)
    eps = 1e-7
    base, _ = q.detect(q.voltage(f))
    ph, _ = q.detect(q.voltage(f, -1j * eps * _gauss(f)))
    expected = omega(f) * _gauss(f)          # d Re Z_T = w L0 chi''
    ratio = (ph - base)[_gauss(f) > 0.1] / expected[_gauss(f) > 0.1]
    assert np.ptp(ratio) < 1e-5 * abs(np.mean(ratio))


def test_ideal_small_chi_dispersion_at_90deg():
    q = _ideal(ref_phase_offset_deg=90.0)
    f = np.linspace(F0 - 0.4, F0 + 0.4, 512)
    eps = 1e-7
    base, _ = q.detect(q.voltage(f))
    ph, _ = q.detect(q.voltage(f, eps * _gauss(f)))
    expected = omega(f) * _gauss(f)          # d Im Z_T = w L0 chi'
    ratio = (ph - base)[_gauss(f) > 0.1] / expected[_gauss(f) > 0.1]
    assert np.ptp(ratio) < 1e-5 * abs(np.mean(ratio))
    # and the matched (absorptive) phase sees no dispersion
    q0 = _ideal()
    b0, _ = q0.detect(q0.voltage(f))
    p0, _ = q0.detect(q0.voltage(f, eps * _gauss(f)))
    assert np.max(np.abs(p0 - b0)) < 1e-6 * np.max(np.abs(ph - base))


def test_default_circuit_small_chi_tracks_absorption():
    q = QMeter(QMeterParams(), F0)
    f = np.linspace(F0 - 0.4, F0 + 0.4, 512)
    base, _ = q.detect(q.voltage(f))
    ph, _ = q.detect(q.voltage(f, -1j * 1e-7 * _gauss(f)))
    # gain is negative by calibration (phase_bg_V < 0), so the correlation is -1
    assert abs(np.corrcoef(ph - base, _gauss(f))[0, 1]) > 0.999


def test_absorption_raises_voltage_at_resonance():
    q = QMeter(QMeterParams(), F0)
    assert abs(q.voltage(F0, -1e-4j)) > abs(q.voltage(F0, 0.0))


def test_calibrated_background_levels():
    p = QMeterParams()
    q = QMeter(p, F0)
    ph, di = q.detect(q.voltage(F0))
    assert ph == pytest.approx(p.phase_bg_V, rel=1e-12)
    assert di == pytest.approx(p.diode_bg_V, rel=1e-12)


def test_dacs_detune_and_restore():
    q = QMeter(QMeterParams(), F0)
    f = np.linspace(F0 - 0.4, F0 + 0.4, 64)
    ph0, di0 = q.detect(q.voltage(f))
    q.set_dac(0.5, 2)
    assert q.dC_pF == pytest.approx(0.5 * q.p.varactor_span_pF)
    assert abs(np.imag(q.tank(F0))) > 0.1
    q.set_dac(0.3, 1)
    assert q.dphi_deg == pytest.approx(0.3 * q.p.phase_dac_span_deg)
    q.set_dac(0.9, 0)                          # channel 0 is a no-op
    assert q.dC_pF == pytest.approx(0.5 * q.p.varactor_span_pF)
    q.set_dac(0.0, 3)
    ph1, di1 = q.detect(q.voltage(f))
    assert np.allclose(ph1, ph0, rtol=1e-12) and np.allclose(di1, di0, rtol=1e-12)
