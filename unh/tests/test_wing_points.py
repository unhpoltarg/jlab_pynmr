"""Wing fit as points per side (unh/wing_points.py): the fraction arithmetic against JLab's own point selection.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_wing_points.py
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from unh import wing_points as wp

JLAB = [0.01, 0.30, 0.70, 0.99]      # pynmr_config.yaml analysis: wings
SIM = [0.01, 0.25, 0.75, 0.99]       # TestSim profiles


def jlab_selection(wings, n):
    """PolyFitSub.result's own rule: bounds = w * len; keep bounds[0] < i < bounds[1] or bounds[2] < i < bounds[3]."""
    b = [w * n for w in wings]
    return np.array([(b[0] < i < b[1]) or (b[2] < i < b[3]) for i in range(n)])


def test_default_counts_match_jlab():
    assert wp.points_per_side(JLAB, 512) == (148, 148)
    assert wp.points_per_side(SIM, 512) == (122, 122)
    assert np.array_equal(wp.used_mask(JLAB, 512), jlab_selection(JLAB, 512))


@pytest.mark.parametrize('n', [2, 10, 60, 100, 148, 200, 249])
def test_n_points_per_side_keeps_the_edge_skip(n):
    w = wp.wings_for(n, JLAB, 512)
    m = jlab_selection(w, 512)                       # what JLab's fit will actually use
    assert m[:256].sum() == n and m[256:].sum() == n
    idx = np.nonzero(m)[0]
    assert idx[0] == 6 and idx[-1] == 506            # JLab's outer 1 % stays out
    assert w[0] == JLAB[0] and w[3] == JLAB[3] and w == sorted(w)


def test_too_many_points_refused():
    top = wp.max_points(JLAB, 512)
    wp.wings_for(top, JLAB, 512)
    with pytest.raises(ValueError):
        wp.wings_for(top + 2, JLAB, 512)
