"""Optimized McClellan Fits result options (unh/mcclellan.py), run with the online fitter's own FitEngine.

Skipped when the sibling LabView-NMR-Fitter folder isn't present.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_mcclellan.py
"""
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from unh import mcclellan as mc

ROOT = mc.fitter_root(mc.load_settings())
pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(ROOT, 'online_fitter', 'engine.py')),
                                reason=f'online fitter not found at {ROOT}')
STREAM = {'signal': 'fitsub', 'amplitude_scale': 1.0}


@pytest.fixture
def fitter():
    engine_mod, protocol = mc.import_fitter(ROOT)
    import deuteron_model as dm                      # the fitter's vendored copy (on sys.path after the import)
    return engine_mod, protocol, dm


def make_line(dm, engine, r, scale=None, phase=None, n=512, cf=32.7, span=0.8, noise=0.0, seed=0):
    """A deuteron line from the fitter's own model, on the axis the streamer and fitter agree on."""
    f = cf + span * (np.arange(n) / n - 0.5)
    engine.set_freq_axis(f, span=span, centfreq=cf)      # as fit_line does: omegD seeded from the window centre
    const = dict(engine._base)
    fm = dm.FastModel(f, const, model=engine.model, with_cube=False)
    s = fm.real(r, const['scale'] if scale is None else scale, const['phase'] if phase is None else phase)
    s = np.asarray(s, float) + 1e-4 * ((f - cf) / span) + noise * np.random.default_rng(seed).standard_normal(n)
    return f, s


def event(f, s, angle=None):
    ev = types.SimpleNamespace(scan=types.SimpleNamespace(freq_list=f, phase=s), fitsub=s, basesub=s)
    if angle is not None:
        ev.quad_ref_deg = angle
    return ev


@pytest.mark.parametrize('P_true', [0.05, 0.25, -0.30,
                                    pytest.param(-0.15, marks=pytest.mark.xfail(strict=True, reason=(
                                        "online fitter's fast fit: small negative P (-5 %, -15 %) runs to the "
                                        "-125 deg phase bound and returns a positive P; -30 % is fine")))])
def test_equilibrium_fit_recovers_P(fitter, P_true):
    engine_mod, protocol, dm = fitter
    eng = engine_mod.FitEngine(material='ND3')
    r = float(engine_mod._r_from_P(P_true))
    f, s = make_line(dm, eng, r, noise=1e-6)
    res = mc.fit_event(eng, protocol, event(f, s), 'equilibrium', STREAM)
    assert res['skipped'] is None and res['P'] == pytest.approx(P_true, abs=0.002)
    assert res['curve'] is not None and np.allclose(res['curve'], s, atol=5e-5)   # the curve lies on the data


def test_quadrature_records_other_than_0_deg_are_skipped(fitter):
    engine_mod, protocol, dm = fitter
    eng = engine_mod.FitEngine(material='ND3')
    f, s = make_line(dm, eng, 1.3)
    for angle in (90, 180, 270):
        res = mc.fit_event(eng, protocol, event(f, s, angle), 'equilibrium', STREAM)
        assert res['skipped'] and np.isnan(res['P'])
    assert eng.status()['n_eq_buffered'] == 0                    # never fed to the Update-Constants buffer
    res = mc.fit_event(eng, protocol, event(f, s, 0), 'equilibrium', STREAM)
    assert res['skipped'] is None and eng.status()['n_eq_buffered'] == 1


def test_update_constants_fixes_a_wrong_scale_and_round_trips(fitter, tmp_path):
    engine_mod, protocol, dm = fitter
    eng = engine_mod.FitEngine(material='ND3')
    P_true = 0.20
    r = float(engine_mod._r_from_P(P_true))
    f, s = make_line(dm, eng, r, scale=3.0 * eng._base['scale'], noise=2e-6)   # amplitude 3x the preset's
    before = mc.fit_event(eng, protocol, event(f, s), 'equilibrium', STREAM)
    for k in range(9):
        mc.fit_event(eng, protocol, event(*make_line(dm, eng, r, scale=3.0 * eng._base['scale'],
                                                     noise=2e-6, seed=k + 1)), 'equilibrium', STREAM)
    eng.update_constants()
    after = mc.fit_event(eng, protocol, event(f, s), 'equilibrium', STREAM)
    assert eng.status()['const_source'] == 'fit'
    assert abs(after['P'] - P_true) < 0.01
    assert not (abs(before['P'] - P_true) < 0.01)                # the preset scale alone gets it wrong
    payload = eng.export_constants()
    other = engine_mod.FitEngine(material='ND3')
    other.import_constants(payload)
    again = mc.fit_event(other, protocol, event(f, s), 'equilibrium', STREAM)
    assert again['P'] == pytest.approx(after['P'], abs=1e-6)


def test_settings_defaults():
    cfg = mc.load_settings()
    assert cfg['material'] in ('ND3', 'd-butanol', 'd-propanediol')
    assert mc.fitter_root({'fitter_path': '../X'}).endswith('X')


def test_line_sign_turns_a_dip_into_the_fitters_upward_line(fitter):
    """At the true 0 deg (UNH convention) positive P is a dip; line_sign -1 hands the fitter an upward line, and the
    curve shown in PyNMR is flipped back onto the dip."""
    engine_mod, protocol, dm = fitter
    eng = engine_mod.FitEngine(material='ND3')
    P_true = 0.25
    f, s = make_line(dm, eng, float(engine_mod._r_from_P(P_true)), noise=1e-6)
    dip = event(f, -s)
    res = mc.fit_event(eng, protocol, dip, 'equilibrium', dict(STREAM, line_sign=-1.0))
    assert res['P'] == pytest.approx(P_true, abs=0.002)
    assert np.allclose(res['curve'], -s, atol=5e-5)
    wrong = mc.fit_event(engine_mod.FitEngine(material='ND3'), protocol, dip, 'equilibrium', STREAM)
    assert not (abs(wrong['P'] - P_true) < 0.01)               # without the flip the fitter can't read the dip
