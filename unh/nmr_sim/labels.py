"""Label-driven simulation: the Run tab's Event Label decides what the simulated target does.

Enabled with ``nmr_sim: labels: enable: True`` (the TestSimQuad profile). The label is set by an
``UNH-HOOK nmr-sim`` line in ``MainWindow.label_changed``; anything not listed below counts as a baseline.

    None, Baseline   line moved out of the window (a baseline); P relaxes towards TE with T1
    TE               thermal equilibrium at the configured field and temperature (5 T, 1 K: about 0.1 %)
    Polarize         a spin-up from wherever P is towards P_inf with time constant tau
    Junk             P frozen; very noisy, with random offset, tilt and bow jumping from chunk to chunk

P is continuous across label changes (a new mode starts from the P the old one had reached).
"""
import threading

import numpy as np

from .timeline import TimelineState, relax_P, spinup_P

_LABEL = {'value': 'None'}
_LOCK = threading.Lock()

MODES = {'none': 'baseline', 'baseline': 'baseline', 'te': 'te', 'polarize': 'polarize', 'junk': 'junk'}


def set_label(label):
    """Called when the operator changes the Event Label (any thread)."""
    with _LOCK:
        _LABEL['value'] = str(label)


def current_label():
    with _LOCK:
        return _LABEL['value']


def mode_of(label):
    return MODES.get(str(label).strip().lower(), 'baseline')


class LabelScenario:
    """P(t) and line position from the label, continuous across changes.

    Args:
        P_te: thermal-equilibrium polarization
        cfg: the ``labels`` settings dict
    """

    def __init__(self, P_te, cfg):
        self.P_te = float(P_te)
        self.cfg = dict(cfg)
        self.mode = None
        self.t0 = 0.0
        self.P0 = self.P_te

    def _P(self, mode, dt):
        c = self.cfg
        if mode == 'te':
            return self.P_te
        if mode == 'polarize':
            return spinup_P(dt, self.P0, float(c['P_inf']), float(c['tau_s']))
        if mode == 'junk':
            return self.P0
        return relax_P(dt, self.P0, self.P_te, float(c['T1_s']))

    def state(self, t_s, label):
        mode = mode_of(label)
        t_s = float(t_s)
        if mode != self.mode:
            if self.mode is not None:
                self.P0 = self._P(self.mode, t_s - self.t0)       # carry P over into the new mode
            self.mode, self.t0 = mode, t_s
        P = self._P(mode, t_s - self.t0)
        offset = float(self.cfg['baseline_offset_MHz']) if mode == 'baseline' else 0.0
        return TimelineState(mode, -1, P, offset, t_s - self.t0)

    def junk(self, rng, freq_MHz, n_sweeps):
        """Extra phase (V) for one Junk chunk: white noise x junk_noise_factor, and a random offset, tilt and bow."""
        c = self.cfg
        f = np.asarray(freq_MHz, dtype=float)
        x = (f - 0.5 * (f.min() + f.max())) / max(0.5 * np.ptp(f), 1e-12)
        bounce = (rng.normal(0.0, c['junk_offset_V']) + rng.normal(0.0, c['junk_slope_V']) * x
                  + rng.normal(0.0, c['junk_bow_V']) * x * x)
        return bounce, float(c['junk_noise_factor'])
