"""Simulator and DAQ adapter: calibration, baseline, clock, contract, config handling."""

import copy

import numpy as np
import pytest

from unh.nmr_sim import simulator as simmod
from unh.nmr_sim.adapter import SimDAQ
from unh.nmr_sim.clock import SimClock
from unh.nmr_sim.params import DEFAULTS, resolve
from unh.nmr_sim.simulator import Simulator

FREQ = 32.7 + 0.4 * np.linspace(-32768, 32767, 512).astype(np.int32) / 32768
TUNE = 0.5 * (FREQ.min() + FREQ.max())


class FakeWall:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _sim(cfg=None, wall=None, speed=60.0):
    c = {"seed": 7, "truth_log_dir": None}
    c.update(cfg or {})
    clock = SimClock(speed, 0.0, wall=wall) if wall else None
    return Simulator(c, TUNE, clock=clock)


@pytest.fixture(autouse=True)
def _reset_singleton():
    simmod.reset_simulator()
    yield
    simmod.reset_simulator()


def test_baseline_segment_has_no_signal_in_window():
    s = _sim()
    ph, _, truth = s.noiseless(FREQ, 10.0)
    assert truth["segment"] == "baseline"
    ph0, _ = s.qmeter.detect(s.qmeter.voltage(FREQ, 0.0))
    sigma_event = s.noise.sigma_phase_V / np.sqrt(640)
    assert np.max(np.abs(ph - ph0)) < 0.1 * sigma_event


def test_calibrated_peak_height():
    cal = {"P": 0.05, "peak_phase_V": 2e-3}
    s = _sim({"calibration": cal,
              "timeline": [{"kind": "hold", "P": 0.05, "duration_s": None}]})
    ph, _, _ = s.noiseless(FREQ, 0.0)
    ph0, _ = s.qmeter.detect(s.qmeter.voltage(FREQ, 0.0))
    assert np.max(np.abs(ph - ph0)) == pytest.approx(2e-3, rel=0.05)


def test_signal_negative_for_positive_P():
    """Negative detector gain: positive P gives a negative phase signal (PyNMR CC < 0)."""
    s = _sim({"timeline": [{"kind": "hold", "P": 0.2, "duration_s": None}]})
    ph, _, _ = s.noiseless(FREQ, 0.0)
    ph0, _ = s.qmeter.detect(s.qmeter.voltage(FREQ, 0.0))
    sig = ph - ph0
    assert abs(sig.min()) > 10 * abs(sig.max())


def test_clock_advances_timeline():
    wall = FakeWall()
    s = _sim(wall=wall, speed=60.0)
    assert s.clock.now_s() == pytest.approx(0.0)
    wall.t += 1.0
    assert s.clock.now_s() == pytest.approx(60.0)
    wall.t += 7200.0 / 60.0
    _, _, truth = s.sweep(FREQ, 64)
    assert truth["segment"] == "te"


def test_daq_contract_and_shared_singleton():
    cfg = {"seed": 3, "truth_log_dir": None, "sweep_time_s": 0.0}
    a = SimDAQ(cfg, FREQ, 64)
    b = SimDAQ(cfg, FREQ, 32)
    assert a.sim is b.sim
    out = a.get_chunk()
    assert isinstance(out, tuple) and len(out) == 4
    num, n, ph, di = out
    assert num == 0 and n == 64
    assert ph.dtype == float and di.dtype == float
    assert ph.shape == di.shape == FREQ.shape
    assert b.get_chunk()[1] == 32
    assert a.set_dac(0.2, 2) is True and b.sim.qmeter.dC_pF > 0


def test_chunk_noise_level():
    cfg = {"seed": 3, "truth_log_dir": None, "sweep_time_s": 0.0}
    d = SimDAQ(cfg, FREQ, 64)
    ph0, _, _ = d.sim.noiseless(FREQ, d.sim.clock.now_s())
    resid = np.concatenate([d.get_chunk()[2] - ph0 for _ in range(50)])
    assert np.std(resid) == pytest.approx(d.sim.noise.sigma_phase_V / 8, rel=0.05)


def test_unknown_keys_raise():
    with pytest.raises(ValueError):
        resolve({"sppeed": 10})
    with pytest.raises(ValueError):
        resolve({"qmeter": {"L0": 1.0}})


def test_input_not_mutated():
    cfg = {"seed": 1, "qmeter": {"L0_uH": 0.3}, "timeline": copy.deepcopy(DEFAULTS["timeline"])}
    before = copy.deepcopy(cfg)
    Simulator(dict(cfg, truth_log_dir=None), TUNE)
    resolve(cfg)
    assert cfg == before


def test_truth_log_written(tmp_path):
    s = _sim({"truth_log_dir": str(tmp_path)})
    s.sweep(FREQ, 64)
    s.sweep(FREQ, 64)
    s._truth_file.close()
    lines = open(s.truth_path).read().splitlines()
    assert lines[0].startswith("# nmr_sim truth log, seed=7")
    assert lines[2].startswith("unix_time,t_sim_s,segment,P,")
    assert len(lines) == 5


def test_custom_material_dict():
    m = {"model": "single", "omegQ1": 0.0273, "A1": 0.04, "eta1": 0.1}
    s = _sim({"material": m})
    ph, _, _ = s.noiseless(FREQ, 9000.0)
    assert np.all(np.isfinite(ph))
