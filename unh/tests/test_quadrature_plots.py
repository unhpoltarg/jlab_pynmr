"""Quadrature Run-tab plots (unh/quadrature/ui.py QuadPlots): the grid switch, live raw and per-angle updates.

Widgets need a QApplication, and the other UNH tests start a bare QCoreApplication in the same process, so
the check runs in its own Python process.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_quadrature_plots.py
"""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

CHECK = r'''
import types
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from unh.quadrature.ui import QuadPlots

app = QApplication([])
live = []
tab = types.SimpleNamespace(raw_pen=pg.mkPen('r'), sub_pen=pg.mkPen('b'), fit_pen=pg.mkPen('y'),
                            fin_pen=pg.mkPen('g'), res_pen=pg.mkPen('m'), parent=types.SimpleNamespace(event=None),
                            update_run_plot=lambda: live.append(1))
top = QWidget()
tab.lowerlayout = QHBoxLayout(top)
for name, title in (('raw_wid', 'Raw Signal'), ('sub_wid', 'Baseline Subtracted'), ('fin_wid', 'Fit Subtracted')):
    w = pg.PlotWidget(title=title)
    setattr(tab, name, w)
    tab.lowerlayout.addWidget(w)
top.show()
p = QuadPlots(tab)
jlab = [tab.raw_wid, tab.sub_wid, tab.fin_wid]
assert all(w.isVisible() for w in jlab) and not p.grid.isVisible()

# on, pair: the grid replaces JLab's three plots; no overlays
p.set_mode(True, [0, 90])
assert p.grid.isVisible() and not any(w.isVisible() for w in jlab)
assert not any(p.curves[(st, a)].isVisible() for st in ('raw', 'sub', 'fin') for a in (180, 270))

x = np.linspace(32.5, 32.9, 5)
def rec(angle, k):
    return types.SimpleNamespace(quad_ref_deg=angle, scan=types.SimpleNamespace(freq_list=x, phase=k * np.ones(5) + 7),
                                 basesub=k * np.ones(5) + 1, fitsub=k * np.arange(5.0), fitcurve=np.ones(5),
                                 rescurve=np.ones(5))
y = lambda st, a: p.curves[(st, a)].getData()[1]

# live raw curve follows the running event's angle; JLab's own update still runs
tab.parent.event = rec(90, 2.0)
tab.update_run_plot()
assert live == [1] and np.allclose(y('raw', 90), 9.0) and y('raw', 0) is None

# a finished record changes only its own angle's curves, in all three stages
p.show_event(rec(0, 1.0))
assert np.allclose(y('raw', 0), 8.0) and np.allclose(y('sub', 0), 2.0) and np.allclose(y('fin', 0), np.arange(5.0))
assert y('sub', 90) is None and np.allclose(p.extra['rescurve', 0].getData()[1], 1.0)
p.show_event(rec(90, 2.0))
assert np.allclose(y('fin', 90), 2 * np.arange(5.0)) and np.allclose(y('fin', 0), np.arange(5.0))
p.show_event(types.SimpleNamespace(scan=types.SimpleNamespace(freq_list=x, phase=np.zeros(5)), fitsub=np.zeros(5)))
assert np.allclose(y('fin', 0), np.arange(5.0))                       # untagged records are ignored

# cycle4: 180/270 drawn as -1 x their record over 0/90 in every stage
p.set_mode(True, [0, 90, 180, 270])
assert all(p.curves[(st, a)].isVisible() for st in ('raw', 'sub', 'fin') for a in (180, 270))
p.show_event(rec(180, 3.0))
p.show_event(rec(270, 4.0))
assert np.allclose(y('raw', 180), -10.0) and np.allclose(y('sub', 270), -5.0) and np.allclose(y('fin', 180), -3 * np.arange(5.0))
assert np.allclose(y('fin', 0), np.arange(5.0)) and np.allclose(y('fin', 90), 2 * np.arange(5.0))
assert [lbl.text for _, lbl in p.legends[('sub', 0)].items] == ['0°', '-1 × 180°']

# back to abba hides the overlays; off shows JLab's plots again
p.set_mode(True, [0, 90, 90, 0])
assert not p.curves[('fin', 180)].isVisible() and p.legends[('fin', 0)].items == []
p.set_mode(False, [0, 90, 90, 0])
assert all(w.isVisible() for w in jlab) and not p.grid.isVisible()

# off: records are ignored; on again starts with empty plots
p.show_event(rec(0, 9.0))
p.set_mode(True, [0, 90])
assert y('fin', 0) is None and y('raw', 90) is None
print('OK')
'''


def test_quadrature_plot_layout_and_per_angle_updates():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=REPO)
    r = subprocess.run([sys.executable, '-c', CHECK], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith('OK'), r.stdout + r.stderr


BASE_CHECK = r'''
import types
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from unh.quadrature.ui import BasePlots

app = QApplication([])
top = QWidget()
bt = types.SimpleNamespace(sel_pen=pg.mkPen('b'), sub_pen=pg.mkPen('g'), right=QVBoxLayout(top),
                           base_wid=pg.PlotWidget(), sub_wid=pg.PlotWidget())
bt.right.addWidget(bt.base_wid)
bt.right.addWidget(bt.sub_wid)
top.show()
p = BasePlots(bt)
assert bt.base_wid.isVisible() and not p.grid.isVisible()
p.set_visible(True)
assert p.grid.isVisible() and not bt.base_wid.isVisible() and not bt.sub_wid.isVisible()

x = np.linspace(32.5, 32.9, 5)
bases = {0: (x, np.full(5, 7.0)), 90: (x, np.full(5, 1.0)), 180: (x, np.full(5, -7.2)), 270: (x, np.full(5, -1.1))}
latest = {0: (x, np.full(5, 7.5)), 90: (x, np.full(5, 1.3)), 180: (x, np.full(5, -7.6))}
p.update(bases, latest)
y = lambda st, a: p.curves[(st, a)].getData()[1]
assert np.allclose(y('base', 0), 7.0) and np.allclose(y('base', 180), 7.2)      # -1 x 180 on the absorptive side
assert np.allclose(y('base', 90), 1.0) and np.allclose(y('base', 270), 1.1)     # -1 x 270 on the dispersive side
assert np.allclose(y('sub', 0), 0.5) and np.allclose(y('sub', 180), 0.4) and np.allclose(y('sub', 90), 0.3)
assert y('sub', 270) is None                                                     # no 270 sweep yet
assert [l.text for _, l in p.legends[('base', 0)].items] == ['0°', '-1 × 180°']
assert p.legends[('sub', 90)].items == []                                        # no overlay, no legend
p.set_visible(False)
assert bt.base_wid.isVisible() and bt.sub_wid.isVisible() and not p.grid.isVisible()
print('OK')
'''


def test_baseline_tab_split_absorptive_dispersive():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=REPO)
    r = subprocess.run([sys.executable, '-c', BASE_CHECK], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith('OK'), r.stdout + r.stderr
