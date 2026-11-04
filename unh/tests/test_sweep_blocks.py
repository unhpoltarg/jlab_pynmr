"""Sweep counts as 64 x N on the Run and Tune tabs (unh/sweep_blocks.py). Widgets need a QApplication and the other UNH tests
start a bare QCoreApplication, so the check runs in its own process.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_sweep_blocks.py
"""
import os
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

CHECK = r'''
import types
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget
from config.config import ConfigItem
from unh.sweep_blocks import attach_sweep_blocks

app = QApplication([])
def make(value):
    controls = {'sweeps': ConfigItem(value, 'Sweeps per Event', QIntValidator(10, 65535)),
                'cc': ConfigItem(1.0, 'CC', QIntValidator())}
    top = QWidget()
    tab = types.SimpleNamespace(parent=types.SimpleNamespace(config=types.SimpleNamespace(controls=controls)),
                                controls_layout=QGridLayout(top), controls_lines={}, controls_labels={})
    for i, k in enumerate(controls):
        tab.controls_lines[k] = QLineEdit(str(controls[k].value))
        tab.controls_labels[k] = QLabel(controls[k].text)
        tab.controls_layout.addWidget(tab.controls_labels[k], i, 0)
        tab.controls_layout.addWidget(tab.controls_lines[k], i, 1)
    tab.lock_button = QPushButton('Unlock', checkable=True)
    top.show()
    tab.top = top                                      # keep the widgets alive
    return tab, attach_sweep_blocks(tab)

tab, sb = make(640)
assert sb.spin.value() == 10 and tab.controls_lines['sweeps'].text() == '640' and not tab.controls_lines['sweeps'].isVisible()
assert not sb.spin.isEnabled()
tab.lock_button.setChecked(True)                      # Unlock: N editable
assert sb.spin.isEnabled()
sb.spin.setValue(3)
assert tab.controls_lines['sweeps'].text() == '192' and sb.total.text() == '= 192'
assert tab.parent.config.controls['sweeps'].value == 640       # applied only by JLab's Set, as before
tab.lock_button.setChecked(False)
assert not sb.spin.isEnabled()
assert sb.spin.maximum() == 1023                       # 64 x 1023 = 65472 fits the 16-bit register
tab, sb = make(100)                                    # not whole chunks: back to the default 64 x 10
assert sb.spin.value() == 10 and tab.parent.config.controls['sweeps'].value == 640
# Tune tab: running average 64 x N, default N = 1, JLab's box kept in step (its textChanged sets to_avg)
from PySide6.QtWidgets import QGroupBox, QHBoxLayout
from unh.sweep_blocks import attach_tune_blocks
tt = types.SimpleNamespace(tune_box=QGroupBox(), avg_value=QLineEdit('32'), running_scan=types.SimpleNamespace(to_avg=32))
tt.tune_box.setLayout(QHBoxLayout())
tt.tune_box.layout().addWidget(QLabel('Sweeps for Running Average:'))
tt.tune_box.layout().addWidget(tt.avg_value)
tt.avg_value.textChanged.connect(lambda: setattr(tt.running_scan, 'to_avg', int(tt.avg_value.text())))
tt.tune_box.show()
tb = attach_tune_blocks(tt)
assert tb.spin.value() == 1 and tt.avg_value.text() == '64' and tt.running_scan.to_avg == 64
assert not tt.avg_value.isVisible() and tb.spin.isEnabled()
tb.spin.setValue(4)
assert tt.running_scan.to_avg == 256 and tb.total.text() == '= 256'
print('OK')
'''


def test_sweep_counts_are_64_times_n():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=REPO)
    r = subprocess.run([sys.executable, '-c', CHECK], cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith('OK'), r.stdout + r.stderr
