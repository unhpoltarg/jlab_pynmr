"""Detector noise and slow drift for chunk-averaged sweeps."""

import math

import numpy as np


class NoiseModel:
    """Zero-mean white Gaussian noise per frequency point, plus optional drift.

    A chunk is the average of n sweeps, so the per-point standard deviation of
    a chunk is sigma / sqrt(n).

    Args:
        rng: numpy Generator (seeded by the caller)
        sigma_phase_V: per-sweep phase noise, V
        sigma_diode_V: per-sweep diode noise, V
        drift_amp_V: amplitude of a slow sinusoidal phase-offset drift, V
        drift_period_s: period of that drift, simulated s
        drift_rate_V_per_h: linear phase-offset drift, V per simulated hour
    """

    def __init__(self, rng, sigma_phase_V=1.5e-3, sigma_diode_V=1.0e-3,
                 drift_amp_V=0.0, drift_period_s=3600.0, drift_rate_V_per_h=0.0):
        self.rng = rng
        self.sigma_phase_V = float(sigma_phase_V)
        self.sigma_diode_V = float(sigma_diode_V)
        self.drift_amp_V = float(drift_amp_V)
        self.drift_period_s = float(drift_period_s)
        self.drift_rate_V_per_h = float(drift_rate_V_per_h)
        self._drift_phase = float(rng.uniform(0.0, 2.0 * math.pi))

    def sample(self, n_pts, n_sweeps):
        """(dphase, ddiode) noise arrays (V) for a chunk averaged over n_sweeps."""
        scale = 1.0 / math.sqrt(n_sweeps)
        dp = self.rng.normal(0.0, self.sigma_phase_V * scale, n_pts)
        dd = self.rng.normal(0.0, self.sigma_diode_V * scale, n_pts)
        return dp, dd

    def drift_V(self, t_s):
        """Phase-offset drift (V) at simulated time t_s (s)."""
        d = self.drift_rate_V_per_h * t_s / 3600.0
        if self.drift_amp_V:
            d += self.drift_amp_V * math.sin(2.0 * math.pi * t_s / self.drift_period_s
                                             + self._drift_phase)
        return d
