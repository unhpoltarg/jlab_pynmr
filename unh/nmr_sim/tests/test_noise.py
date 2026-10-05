"""Noise: 1/sqrt(N) scaling, zero mean, reproducibility, drift."""

import numpy as np
import pytest

from unh.nmr_sim.noise import NoiseModel


@pytest.mark.parametrize("n", [16, 64, 1024])
def test_std_scales_and_mean_zero(n):
    nm = NoiseModel(np.random.default_rng(5), sigma_phase_V=1.5e-3, sigma_diode_V=1e-3)
    M = 400
    dp = np.concatenate([nm.sample(512, n)[0] for _ in range(M)])
    expected = 1.5e-3 / np.sqrt(n)
    assert np.std(dp) == pytest.approx(expected, rel=0.03)
    assert abs(np.mean(dp)) < 3 * expected / np.sqrt(dp.size)


def test_seed_reproducible():
    a = NoiseModel(np.random.default_rng(42)).sample(512, 64)
    b = NoiseModel(np.random.default_rng(42)).sample(512, 64)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_drift_off_by_default_and_linear_rate():
    nm = NoiseModel(np.random.default_rng(1))
    assert nm.drift_V(1234.0) == 0.0
    nm = NoiseModel(np.random.default_rng(1), drift_rate_V_per_h=2e-3)
    assert nm.drift_V(7200.0) == pytest.approx(4e-3)
