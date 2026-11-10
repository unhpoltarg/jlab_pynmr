"""Phase Tune Control during Auto Tune and Auto Calibrate Phase (unh/quadrature/ui.py, controller.on_cal_finished).

- Each scan step shows the phase DAC being measured on the Phase Tune spinbox and slider, without sending it.
- The Phase and Diode Tune controls are locked during the scan (a knob moved then would write the box mid-scan),
  and stay locked afterwards if a run is going, as JLab has them.
- At the end the controls show the tune the box was left at, and the Tune tab's stored DAC write is that tune,
  so a resumed Tune loop doesn't send the setting from before the scan.

Widgets need a QApplication, and the other UNH tests start a bare QCoreApplication in the same process, so
the check runs in its own Python process.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_autotune_display.py
"""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

CHECK = r'''
import types
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLabel, QSlider
from unh.quadrature.ui import QuadUI, TUNE_KNOBS, lock_tune_knobs
from unh.quadrature.controller import QuadController

app = QApplication([])
sent = []
tune = types.SimpleNamespace()                       # the Tune tab's knobs, set up as JLab's tune_tab.py has them
tune.phase_slider = QSlider(Qt.Horizontal)
tune.phase_slider.setRange(0, 1000)
tune.phase_spin = QDoubleSpinBox()
tune.phase_spin.setDecimals(2)
tune.phase_spin.setRange(0, 100)
tune.diode_slider = QSlider(Qt.Horizontal)
tune.diode_slider.setRange(0, 1000)
tune.diode_spin = QDoubleSpinBox()
tune.diode_spin.setDecimals(3)
tune.diode_spin.setRange(0, 100)
tune.phase_spin.setValue(30.0)
tune.diode_plot, tune.phase_plot = pg.PlotDataItem(), pg.PlotDataItem()
tune.phase_spin.valueChanged.connect(sent.append)    # stand-ins for JLab's slots, which send to the box
tune.phase_slider.valueChanged.connect(sent.append)
tune.dac_v, tune.dac_c = 0.30, 1                     # the Tune tab's last DAC write, from before the scan

running = [False]
config = types.SimpleNamespace(phase_vout=0.30, freq_list=np.linspace(32.5, 32.9, 8))
mw = types.SimpleNamespace(tune_tab=tune, config=config, run_in_progress=lambda: running[0],
                           run_toggle=lambda: lock_tune_knobs(tune, False, running[0]))
ui = types.SimpleNamespace(ctrl=types.SimpleNamespace(mw=mw), cal_label=QLabel(), cal_points=[],
                           cal_phase=pg.PlotDataItem(), cal_diode=pg.PlotDataItem(), _scan_view=lambda title: None)
enabled = lambda: [getattr(tune, n).isEnabled() for n in TUNE_KNOBS]

QuadUI.autotune_started(ui)
assert not any(enabled())                            # locked for the scan
for v in (0.27, 0.285, 0.30, 0.315, 0.33):           # each step shows the setting being measured
    QuadUI.cal_progress(ui, {'step': 1, 'of': 5, 'vout': v, 't_s': 1.0}, what='Auto Tune pass 1')
    assert abs(tune.phase_spin.value() - v * 100) < 1e-9 and tune.phase_slider.value() == round(v * 1000)
assert sent == []                                    # shown only, never sent to the box

config.phase_vout = 0.313                            # Auto Tune's new tune; the thread left the DAC there
ctrl = types.SimpleNamespace(mw=mw, _resume_tune=False,
                             ui=types.SimpleNamespace(refresh=lambda: None, scan_finished=lambda: QuadUI.scan_finished(ui)))
QuadController.on_cal_finished(ctrl)
assert abs(tune.phase_spin.value() - 31.3) < 1e-9 and tune.phase_slider.value() == 313
assert tune.dac_v == 0.313 and tune.dac_c == 1       # a resumed Tune loop re-sends the new tune, not 0.30
assert all(enabled()) and sent == []

QuadUI.cal_started(ui)                               # Auto Calibrate Phase locks them too
assert not any(enabled())
running[0] = True                                    # a run going when the scan ends: JLab keeps them locked
QuadUI.scan_finished(ui)
assert not any(enabled())
print('OK')
'''


def test_phase_tune_control_follows_the_scan_and_gets_the_tune_back():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=REPO)
    r = subprocess.run([sys.executable, '-c', CHECK], cwd=REPO, env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith('OK'), r.stdout + r.stderr
