"""Tests for the TE fixes (UNH-HOOK te-fix): report folder, Run-tab CC display, missing temperatures.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_te_fix.py
"""
import glob
import json
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from core.calculations import TE
import gui.main_window as mw
from gui.tabs.te_tab import TETab

TEMP_PV = 'TGT:PT12:VaporPressure_T'


class Box:
    """Stand-in for the Run tab's CC QLineEdit."""
    def __init__(self, text):
        self._text = text

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class Recorder:
    """Stand-in for a widget method: remembers the arguments of every call."""
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def te_tab_stub(temps, te_dir='te'):
    """Just enough of a TETab for take_te/use_te: two selected history points with the given temperatures."""
    stamps = [1000.0, 1060.0]
    tab = types.SimpleNamespace()
    tab.te_data = np.array([[stamps[0], -0.010], [stamps[1], -0.011]])
    tab.hist_points = {s: types.SimpleNamespace(epics_reads=reads) for s, reads in zip(stamps, temps)}
    tab.parent = types.SimpleNamespace(settings={'epics_settings': {'epics_temp': TEMP_PV}, 'te_dir': te_dir},
                                       set_cc=Recorder())
    tab.teselect_label = types.SimpleNamespace(setText=Recorder())
    tab.set_but = types.SimpleNamespace(setEnabled=Recorder())
    tab.species_box = types.SimpleNamespace(currentText=Recorder('Deuteron'))
    tab.field_value = types.SimpleNamespace(text=Recorder('5.0'))
    tab.te_temp = lambda stamp: TETab.te_temp(tab, stamp)
    return tab


def test_print_te_creates_its_folder(tmp_path):
    te = TE('Deuteron', 5.0, [-0.010, -0.011], [1.0, 1.0])
    folder = tmp_path / 'not' / 'there' / 'te'
    te.print_te(str(folder))
    files = glob.glob(str(folder / 'Deuteron-*.json'))
    assert len(files) == 1
    with open(files[0]) as f:
        assert json.load(f)['cc'] == pytest.approx(te.cc)


def test_set_cc_updates_run_tab_box():
    main = types.SimpleNamespace(config=types.SimpleNamespace(controls={'cc': types.SimpleNamespace(value=-0.08)}),
                                 run_tab=types.SimpleNamespace(controls_lines={'cc': Box('-0.08')}))
    mw.MainWindow.set_cc(main, -0.0512)
    assert main.config.controls['cc'].value == -0.0512
    assert float(main.run_tab.controls_lines['cc'].text()) == -0.0512   # what save_session will store


def test_set_cc_before_run_tab_exists():
    main = types.SimpleNamespace(config=types.SimpleNamespace(controls={'cc': types.SimpleNamespace(value=-0.08)}))
    mw.MainWindow.set_cc(main, -0.05)
    assert main.config.controls['cc'].value == -0.05


@pytest.mark.parametrize('reads', [{}, {TEMP_PV: 0.0}, {TEMP_PV: None}])
def test_take_te_refuses_missing_temperature(reads):
    tab = te_tab_stub([reads, {TEMP_PV: 1.0}])
    TETab.take_te(tab)
    assert not hasattr(tab, 'te')
    assert 'TE not taken: 1 of 2' in tab.teselect_label.setText.calls[-1][0]
    assert tab.set_but.setEnabled.calls[-1] == (False,)


def test_take_te_with_temperatures():
    tab = te_tab_stub([{TEMP_PV: 1.0}, {TEMP_PV: 1.02}])
    TETab.take_te(tab)
    assert np.isfinite(tab.te.cc) and tab.te.num == 2
    assert tab.set_but.setEnabled.calls[-1] == (True,)


def test_use_te_writes_to_te_dir_and_sets_cc(tmp_path):
    tab = te_tab_stub([{TEMP_PV: 1.0}, {TEMP_PV: 1.02}], te_dir=str(tmp_path / 'te'))
    TETab.take_te(tab)
    TETab.use_te(tab)
    assert len(glob.glob(str(tmp_path / 'te' / '*.json'))) == 1
    assert tab.parent.set_cc.calls == [(tab.te.cc,)]
