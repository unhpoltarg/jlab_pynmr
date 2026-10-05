"""Tests for the interactive NMR frequency window (center frequency and half-width set from the Run tab).

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest tests/test_freq_window.py
"""
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from config import Config
import gui.main_window as mw


SETTINGS = {'steps': 512}


def channel(cent=32.7, mod=400.0):
    return {'name': 'Deuteron5T', 'species': 'deuteron', 'cent_freq': cent, 'mod_freq': mod,
            'power': 400.0, 'sweep_file': 'tri'}


class FakeMain:
    """Stand-in for MainWindow carrying only what the window methods use."""
    replace_config = mw.MainWindow.replace_config
    set_window = mw.MainWindow.set_window
    apply_pending_window = mw.MainWindow.apply_pending_window

    def __init__(self, running=False):
        self.settings = SETTINGS
        self.config = Config(channel(), SETTINGS)
        self.service = None
        self.pending_window = None
        self.running = running
        self.messages = []
        self.status_bar = types.SimpleNamespace(showMessage=self.messages.append)

    def run_in_progress(self):
        return self.running


@pytest.fixture(autouse=True)
def no_rs(monkeypatch):
    """Record R&S programming instead of opening a telnet connection."""
    calls = []
    monkeypatch.setattr(mw, 'RS_Connection', lambda config: calls.append(config))
    monkeypatch.setattr(mw, 'EventData', lambda parent: types.SimpleNamespace(config=parent.config))
    return calls


def test_freq_list_spans_center_plus_minus_halfwidth():
    """freq_list (MHz) runs from cent - mod to cent + mod (mod in kHz) in `steps` points."""
    c = Config(channel(cent=32.77, mod=300.0), SETTINGS)
    assert len(c.freq_list) == 512 and len(c.freq_bytes) == 512
    assert c.freq_list[0] == pytest.approx(32.77 - 0.300)
    assert c.freq_list[-1] == pytest.approx(32.77 + 0.300, abs=1e-5)   # top int is 32767/32768 of full deviation
    assert np.all(np.diff(c.freq_list) > 0)


def test_freq_bytes_unchanged_by_window():
    """The FPGA table is the 16-bit modulation word, independent of center and width (R&S scales it)."""
    a = Config(channel(32.7, 400.0), SETTINGS)
    b = Config(channel(212.882, 150.0), SETTINGS)
    assert a.freq_bytes == b.freq_bytes


def test_idle_window_change_applies_now_without_mutating_old(no_rs):
    m = FakeMain(running=False)
    old_config, old_channel = m.config, m.config.channel
    old_freqs = old_config.freq_list.copy()
    m.set_window(32.77, 300.0)
    assert m.config is not old_config
    assert m.config.channel['cent_freq'] == 32.77 and m.config.channel['mod_freq'] == 300.0
    assert old_channel['cent_freq'] == 32.7 and old_channel['mod_freq'] == 400.0   # old dict untouched
    np.testing.assert_array_equal(old_config.freq_list, old_freqs)                  # old axis untouched
    assert m.pending_window is None
    assert len(no_rs) == 1 and no_rs[0] is m.config                                 # R&S reprogrammed
    assert m.event.config is m.config
    assert any('NMR window changed' in s for s in m.messages)


def test_running_window_change_waits_for_next_event(no_rs):
    m = FakeMain(running=True)
    in_progress = m.config
    m.set_window(32.80, 250.0)
    assert m.config is in_progress and m.pending_window == (32.80, 250.0)
    assert no_rs == []                                       # nothing sent mid-event
    assert m.apply_pending_window() is True                  # what RunTab.start_thread does before new_event()
    assert m.config.channel['cent_freq'] == 32.80 and m.config.channel['mod_freq'] == 250.0
    assert in_progress.channel['cent_freq'] == 32.7          # the finished event's config keeps its window
    assert m.apply_pending_window() is False                 # nothing left pending


def recorded_signal_config(cent, mod):
    settings = {'steps': 512, 'daq_type': 'Test', 'test_signal': 'utils/d_signal_event.txt', 'num_per_chunk': 64}
    return Config(channel(cent, mod), settings)


@pytest.fixture
def repo_root(monkeypatch):
    monkeypatch.chdir(os.path.join(os.path.dirname(__file__), '..'))


def test_test_daq_matches_recording_on_its_own_window(repo_root):
    """Window equal to the recording's (31.83 MHz ± 400 kHz) returns the recorded signal unchanged."""
    import json
    from hardware.daq import DAQConnection
    rec = json.loads(open('utils/d_signal_event.txt').read().strip().split('\n')[-1])
    daq = DAQConnection(recorded_signal_config(31.83, 400.0), timeout=1)
    np.testing.assert_allclose(daq.test_phase, rec['phase'], rtol=0, atol=1e-12)
    assert daq.test_in_range.all()


def test_test_daq_holds_edge_values_outside_recording(repo_root):
    """Requested points outside the recorded 31.43-32.23 MHz hold the nearest recorded edge value."""
    import json
    from hardware.daq import DAQConnection
    rec = json.loads(open('utils/d_signal_event.txt').read().strip().split('\n')[-1])
    for cent, side in ((32.2, 'above'), (31.46, 'below')):   # each window hangs off one edge of the recording
        daq = DAQConnection(recorded_signal_config(cent, 400.0), timeout=1)
        freqs = daq.config.freq_list
        outside = freqs > rec['freq_list'][-1] if side == 'above' else freqs < rec['freq_list'][0]
        assert outside.any() and (~outside).any()
        np.testing.assert_array_equal(daq.test_in_range, ~outside)
        edge = rec['phase'][-1] if side == 'above' else rec['phase'][0]
        assert np.all(daq.test_phase[outside] == edge)
        _, n, phase, diode = daq.get_chunk()
        assert np.all(np.abs(phase[outside] - edge) < 1e-3)   # edge value plus test noise


def test_controls_and_tune_carry_over(no_rs):
    m = FakeMain()
    m.config.controls['sweeps'].value = 1000
    m.config.controls['cc'].value = 5.2
    m.config.phase_vout, m.config.diode_vout = 0.31, 0.27
    m.set_window(32.77, 400.0)
    assert m.config.controls['sweeps'].value == 1000
    assert m.config.controls['cc'].value == 5.2
    assert (m.config.phase_vout, m.config.diode_vout) == (0.31, 0.27)
