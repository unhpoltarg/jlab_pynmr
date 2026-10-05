"""Timeline: segment limits, continuity, offsets, hold-at-end, validation."""

import pytest

from nmr_sim.timeline import Timeline

P_TE = 0.001
SEGS = [
    {"name": "baseline", "kind": "hold", "P": "te", "duration_s": 100.0, "line_offset_MHz": 1.2},
    {"name": "te", "kind": "hold", "duration_s": 50.0},
    {"name": "spinup", "kind": "spinup", "P_inf": 0.4, "tau_s": 1000.0, "duration_s": 20000.0},
    {"name": "relax", "kind": "relax", "T1_s": 500.0, "duration_s": 10000.0},
]


def test_segments_and_offsets():
    tl = Timeline(SEGS, P_TE)
    s = tl.state(10.0)
    assert (s.name, s.P, s.line_offset_MHz) == ("baseline", P_TE, 1.2)
    s = tl.state(120.0)
    assert (s.name, s.P, s.line_offset_MHz) == ("te", P_TE, 0.0)


def test_spinup_limits():
    tl = Timeline(SEGS, P_TE)
    assert tl.state(150.0).P == pytest.approx(P_TE, abs=1e-15)
    assert tl.state(150.0 + 10 * 1000.0).P == pytest.approx(0.4, abs=5e-5)


def test_relax_to_te_and_hold_at_end():
    tl = Timeline(SEGS, P_TE)
    end = 150.0 + 20000.0 + 10000.0
    assert tl.state(end - 1e-6).P == pytest.approx(P_TE, abs=5e-5)
    after = tl.state(end + 1e6)
    assert after.name == "relax" and after.P == pytest.approx(tl.state(end - 1e-9).P, abs=1e-12)


@pytest.mark.parametrize("t_boundary", [100.0, 150.0, 20150.0])
def test_continuity(t_boundary):
    tl = Timeline(SEGS, P_TE)
    assert tl.state(t_boundary - 1e-6).P == pytest.approx(tl.state(t_boundary).P, abs=1e-8)


def test_open_ended_last_segment():
    tl = Timeline([{"kind": "hold", "P": 0.1, "duration_s": None}], P_TE)
    assert tl.state(1e9).P == 0.1


def test_validation():
    with pytest.raises(ValueError):
        Timeline([{"kind": "hold", "duration_s": None}, {"kind": "hold", "duration_s": 1}], P_TE)
    with pytest.raises(ValueError):
        Timeline([{"kind": "spinup", "P_inf": 0.4, "tau": 1, "duration_s": 1}], P_TE)
    with pytest.raises(ValueError):
        Timeline([{"kind": "warp", "duration_s": 1}], P_TE)
    with pytest.raises(ValueError):
        Timeline([{"kind": "hold", "P": 1.2, "duration_s": 1}], P_TE)
