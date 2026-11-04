"""Label-driven simulation (labels.py): the Event Label decides what the simulated target does."""
import numpy as np
import pytest

from unh.nmr_sim import labels
from unh.nmr_sim.params import DEFAULTS, resolve
from unh.nmr_sim.simulator import Simulator
from unh.nmr_sim.timeline import p_te


class Clock:
    def __init__(self):
        self.t = 0.0

    def now_s(self):
        return self.t

    def wall_s(self):
        return self.t


def test_label_names():
    assert [labels.mode_of(x) for x in ('None', 'Baseline', 'TE', 'Polarize', 'Junk', 'junk', 'anything')] == \
        ['baseline', 'baseline', 'te', 'polarize', 'junk', 'junk', 'baseline']


def test_P_is_continuous_across_label_changes():
    cfg = dict(DEFAULTS['labels'], enable=True)
    s = labels.LabelScenario(0.001, cfg)
    assert s.state(0.0, 'None').P == pytest.approx(0.001) and s.state(0.0, 'None').line_offset_MHz == 1.2
    assert s.state(10.0, 'Polarize').P == pytest.approx(0.001)                 # starts where it was
    P = s.state(10.0 + cfg['tau_s'], 'Polarize').P
    assert P == pytest.approx(0.40 + (0.001 - 0.40) * np.exp(-1.0), rel=1e-9)
    t = 10.0 + cfg['tau_s']
    P = 0.40 + (0.001 - 0.40) * np.exp(-(cfg['tau_s'] + 500.0) / cfg['tau_s'])   # still spinning up until the switch
    assert s.state(t + 500.0, 'Junk').P == pytest.approx(P)
    assert s.state(t + 900.0, 'Junk').P == pytest.approx(P)                     # then frozen
    b = s.state(t + 500.0 + cfg['T1_s'], 'Baseline')
    assert b.P == pytest.approx(P) and b.line_offset_MHz == 1.2                 # relaxation starts at the switch
    assert s.state(t + 500.0 + 2 * cfg['T1_s'], 'Baseline').P == pytest.approx(0.001 + (P - 0.001) * np.exp(-1.0))
    assert s.state(t + 1e6, 'TE').P == pytest.approx(0.001) and s.state(t + 1e6, 'TE').line_offset_MHz == 0.0


def test_te_at_5T_1K_is_about_a_tenth_of_a_percent():
    assert p_te(32.7, 1.0) == pytest.approx(0.00105, rel=0.02)


def test_simulator_follows_the_label():
    cfg = resolve({'seed': 3, 'labels': {'enable': True}, 'truth_log_dir': None, 'sweep_time_s': 0.0})
    clk = Clock()
    sim = Simulator(cfg, 32.7, clock=clk)
    f = np.linspace(32.3, 33.1, 256)
    try:
        labels.set_label('None')
        ph_base, _, tr = sim.sweep(f, 64)
        assert tr['segment'] == 'baseline' and tr['line_offset_MHz'] == 1.2
        labels.set_label('TE')
        _, _, tr = sim.sweep(f, 64)
        assert tr['segment'] == 'te' and tr['P'] == pytest.approx(sim.P_te)
        labels.set_label('Polarize')
        sim.sweep(f, 64)
        clk.t = 3000.0
        _, _, tr = sim.sweep(f, 64)
        assert tr['segment'] == 'polarize' and 0.2 < tr['P'] < 0.40
        calm = np.std(sim.sweep(f, 64)[0] - sim.sweep(f, 64)[0])    # same moment: the difference is the noise
        labels.set_label('Junk')
        sim.sweep(f, 64)
        noisy = np.std(sim.sweep(f, 64)[0] - sim.sweep(f, 64)[0])
        assert noisy > 20 * calm
    finally:
        labels.set_label('None')
