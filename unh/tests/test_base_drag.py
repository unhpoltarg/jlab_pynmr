"""Baseline tab: a drag selection (no 'clicked' signal) still builds the baseline (UNH-HOOK base-drag).

Builds the real MainWindow in the TestSimQuad profile in its own process (widgets need a QApplication; the other
tests start a QCoreApplication), writes a small cycle4 event file, opens it on the Baseline tab and selects rows
through the selection model only, as a mouse drag does.
"""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

CHECK = r'''
import json, os, shutil, sys, tempfile
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QItemSelection, QItemSelectionModel
app = QApplication([])
tmp = tempfile.mkdtemp()
os.chdir(sys.argv[1])
from gui.main_window import MainWindow
gui = MainWindow('pynmr_config.yaml', profile='TestSimQuad')
bt = gui.base_tab
f = list(gui.config.freq_list)
path = os.path.join(tmp, 'events.txt')
with open(path, 'w') as fh:
    for i in range(8):
        a = (0, 90, 180, 270)[i % 4]
        v = {0: 0.238, 90: 0.4076, 180: 0.5063, 270: 0.5922}[a]
        fh.write(json.dumps({'stop_time': '2026-11-04 12:00:%02d+00:00' % i, 'stop_stamp': 1000.0 + i,
                             'channel': {'name': 'Deuteron5T', 'cent_freq': 32.7, 'mod_freq': 400.0},
                             'freq_list': f, 'sweeps': 64, 'phase': [float(a) + i] * len(f), 'label': 'Baseline',
                             'quad_ref_deg': a, 'phase_vout': v}) + '\n')
bt.basefile_path = path
bt.open_basefile()
model, sel = bt.event_model, bt.event_table.selectionModel()
rng = QItemSelection(model.index(0, 0), model.index(model.rowCount() - 1, model.columnCount() - 1))
sel.select(rng, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)    # as a drag does: no clicked()
qb = bt.quad_bases
assert qb and sorted(qb) == [0, 90, 180, 270], qb
assert all(len(qb[a]['base_stamps']) == 2 for a in qb)
assert np.allclose(qb[0]['phase'], 2.0) and np.allclose(qb[90]['phase'], 93.0)   # (0+0, 0+4)/2, (90+1, 90+5)/2
bt.set_base()
assert sorted(gui.quadrature.baselines) == [0, 90, 180, 270]
import datetime
bt.set_base()                                   # a second press used to turn the dates into text (JLab bug)
assert isinstance(gui.baseline.stop_time, datetime.datetime)
assert all(isinstance(b.stop_time, datetime.datetime) for b in gui.quadrature.baselines.values())
from gui.tabs.analysis_modules import StandardBase
ev = gui.event
gui.set_event_base()
assert isinstance(ev.base_time, datetime.datetime)
print('OK', flush=True)
os._exit(0)
'''


def test_drag_selection_sets_all_four_baselines(tmp_path):
    work = tmp_path / 'pynmr'
    import shutil
    top = os.path.abspath(REPO)

    def skip(d, names):                                  # only the top-level data folders, not core/data_models.py
        if os.path.abspath(d) == top:
            return [n for n in names if n in ('.git', 'log', '.claude') or n.startswith('data')]
        return [n for n in names if n == '__pycache__']
    shutil.copytree(REPO, work, ignore=skip)
    for name in ('simquad_session.yaml', 'simquad_history.json'):
        p = work / 'config' / name
        if p.exists():
            p.unlink()
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(work))
    r = subprocess.run([sys.executable, '-c', CHECK, str(work)], cwd=str(work), env=env, capture_output=True,
                       text=True, timeout=240)
    assert r.returncode == 0 and 'OK' in r.stdout, r.stdout[-3000:] + r.stderr[-3000:]
