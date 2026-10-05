"""Lineshape port: inverse of ratio_P, TE consistency, source parity, Kramers-Kronig sign."""

import importlib.util
import math
import os
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import hilbert

from nmr_sim.lineshape import FastModel, MATERIALS, ratio_P, ratio_Q, r_of_P
from nmr_sim.susceptibility import DISPERSION_SIGN
from nmr_sim.timeline import p_te, H_J_S, KB_J_PER_K

ND3 = "deuterated ammonia (Dec 2024)"
DBUT = "irradiated d-butanol (Dec 2025, 13th/15th)"


def _source_module():
    root = os.environ.get("MCCLELLAN_FITS_DIR")
    root = Path(root) if root else Path(__file__).resolve().parents[3] / "optimized-mcclellan-fits"
    path = root / "fitter" / "deuteron_model.py"
    if not path.exists():
        pytest.skip(f"source model not found at {path}")
    spec = importlib.util.spec_from_file_location("_mcclellan_deuteron_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_r_of_P_roundtrip():
    P = np.linspace(-0.99, 0.99, 397)
    assert np.allclose(ratio_P(r_of_P(P)), P, atol=1e-12, rtol=0)
    assert r_of_P(0.0) == pytest.approx(1.0, abs=1e-15)


def test_r_of_P_rejects_unphysical():
    with pytest.raises(ValueError):
        r_of_P(1.0)


def test_p_te_matches_ratio_P():
    f, T = 32.7, 1.0
    x = H_J_S * f * 1e6 / (KB_J_PER_K * T)
    assert p_te(f, T) == pytest.approx(ratio_P(math.exp(x)), rel=1e-12)
    # high-temperature limit P ~ 2x/3
    assert p_te(f, T) == pytest.approx(2 * x / 3, rel=1e-5)


def test_Q_zero_at_P_zero():
    assert ratio_Q(r_of_P(0.0)) == pytest.approx(0.0, abs=1e-15)


@pytest.mark.parametrize("name", [ND3, DBUT])
def test_matches_source_fastmodel(name):
    src = _source_module()
    const = dict(MATERIALS[name], omegD=32.7)
    f = np.linspace(32.2, 33.2, 512)
    ours = FastModel(f, const, const["model"])
    theirs = src.FastModel(f, const, const["model"])
    for P in (0.001, 0.2, 0.45, -0.3):
        r = r_of_P(P)
        for phase in (0.0, 0.1, math.pi / 2):
            a = ours.real(r, 0.004, phase)
            b = theirs.real(r, 0.004, phase)
            assert np.allclose(a, b, rtol=1e-12, atol=1e-15 * np.max(np.abs(b)))


@pytest.mark.parametrize("name", [ND3, DBUT])
def test_parts_equal_real_at_0_and_90(name):
    const = dict(MATERIALS[name], omegD=32.7)
    f = np.linspace(32.2, 33.2, 512)
    fm = FastModel(f, const, const["model"])
    r = r_of_P(0.3)
    A, D = fm.parts(r)
    assert np.allclose(A, fm.real(r, 1.0, 0.0), rtol=1e-12, atol=0)
    assert np.allclose(D, fm.real(r, 1.0, math.pi / 2), rtol=0, atol=1e-12 * np.max(np.abs(D)))


@pytest.mark.parametrize("name", [ND3, DBUT])
@pytest.mark.parametrize("P", [0.3, -0.3])
def test_kramers_kronig_sign(name, P):
    """chi' = -H[chi''] (e^{+iwt}, chi = chi' - i chi''): fixes DISPERSION_SIGN = +1."""
    const = dict(MATERIALS[name], omegD=32.7)
    f = np.linspace(32.7 - 3, 32.7 + 3, 2 ** 14, endpoint=False)
    A, D = FastModel(f, const, const["model"]).parts(r_of_P(P))
    kk = -np.imag(hilbert(A))
    sel = np.abs(f - 32.7) < 0.5
    corr = np.corrcoef(DISPERSION_SIGN * D[sel], kk[sel])[0, 1]
    assert corr > 0.999
