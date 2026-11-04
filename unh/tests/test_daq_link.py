"""Tests for the daq-link hooks: clean closes of the FPGA box connections, and the stop command after errors.

A fake box on 127.0.0.1 stands in for the FPGA. Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests/test_daq_link.py
"""
import os
import socket
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import hardware.daq as daq_mod
from hardware.tcp import TCP


def fpga_config(port, close_wait=0.5):
    return types.SimpleNamespace(settings={
        'daq_type': 'FPGA', 'steps': 4,
        'fpga_settings': {'ip': '127.0.0.1', 'port': port, 'tcp_buffer': 1460, 'phase_cal': 1, 'diode_cal': 1,
                          'phase_adc_number': 1, 'close_wait': close_wait},
    })


class FakeBox:
    """TCP listener that sends `extra` unread bytes after accepting, then reports how the client closed.

    Args:
        extra: bytes sent to the client that the client never asks for
        closes_back: if True, the box closes its side as soon as the client does
    """

    def __init__(self, extra=b'', closes_back=True):
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.extra = extra
        self.closes_back = closes_back
        self.saw = None
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        conn, _ = self.srv.accept()
        if self.extra:
            conn.sendall(self.extra)
        conn.settimeout(5)
        try:
            self.saw = 'normal close' if conn.recv(16) == b'' else 'data'
        except OSError as e:
            self.saw = f'reset ({e.__class__.__name__})'
        if not self.closes_back:
            self.release.wait(5)
        conn.close()

    def finish(self):
        self.release.set()
        self.thread.join(5)
        self.srv.close()
        return self.saw


def test_plain_close_with_unread_data_resets_the_connection():
    """Why the hook exists: JLab's close (at garbage collection) aborts the connection if the box's data is unread"""
    box = FakeBox(extra=b'x' * 5000)
    s = socket.create_connection(('127.0.0.1', box.port))
    time.sleep(0.2)
    s.close()
    assert box.finish().startswith('reset')


def test_close_is_normal_even_with_unread_data():
    box = FakeBox(extra=b'x' * 5000)
    tcp = TCP(fpga_config(box.port), timeout=1)
    time.sleep(0.2)
    how = tcp.close()
    assert box.finish() == 'normal close'
    assert how.startswith('box closed its side')
    assert 'discarded 5000 unread bytes' in how


def test_close_waits_at_most_close_wait_for_the_box():
    box = FakeBox(closes_back=False)
    tcp = TCP(fpga_config(box.port, close_wait=0.3), timeout=1)
    start = time.monotonic()
    how = tcp.close()
    took = time.monotonic() - start
    assert box.finish() == 'normal close'
    assert 'did not close its side' in how
    assert 0.25 < took < 1.0


def test_close_twice_is_harmless():
    box = FakeBox()
    tcp = TCP(fpga_config(box.port), timeout=1)
    tcp.close()
    assert tcp.close() == 'already closed'
    box.finish()


class FakeLink:
    """Stand-in for hardware UDP/TCP that records calls"""

    def __init__(self, *args, fail=False, **kwargs):
        if fail:
            raise ConnectionRefusedError('box not answering')
        self.ip, self.port = '127.0.0.1', 1028
        self.calls = []

    def close(self):
        self.calls.append('close')
        return 'box closed its side after 1 ms'

    def int_sweep(self):
        self.calls.append('int_sweep')
        return True


def test_daq_connection_closes_udp_when_tcp_connect_fails(monkeypatch):
    made = []

    def udp(*args):
        made.append(FakeLink())
        return made[-1]

    monkeypatch.setattr(daq_mod, 'UDP', udp)
    monkeypatch.setattr(daq_mod, 'TCP', lambda *a: FakeLink(fail=True))
    with pytest.raises(ConnectionRefusedError):
        daq_mod.DAQConnection(fpga_config(1028), 1)
    assert made[0].calls == ['close']


def test_daq_connection_close_closes_both_and_reports_tcp(monkeypatch):
    monkeypatch.setattr(daq_mod, 'UDP', lambda *a: FakeLink())
    monkeypatch.setattr(daq_mod, 'TCP', lambda *a: FakeLink())
    daq = daq_mod.DAQConnection(fpga_config(1028), 1)
    assert daq.close() == 'box closed its side after 1 ms'
    assert daq.udp.calls == ['close'] and daq.tcp.calls == ['close']


class FakeDAQ:
    """DAQConnection stand-in whose reads time out, as when the box stops answering"""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def start_sweeps(self):
        self.calls.append('start')

    def get_chunk(self):
        raise socket.timeout('timed out')

    def set_dac(self, *args):
        return True

    def abort(self):
        self.calls.append('abort')

    def stop(self):
        self.calls.append('stop')

    def close(self):
        self.calls.append('close')
        return 'box closed its side after 1 ms'


def run_config():
    sweeps = types.SimpleNamespace(value=64)
    return types.SimpleNamespace(controls={'sweeps': sweeps},
                                 settings={'num_per_chunk': 64, 'tune_per_chunk': 32, 'daq_type': 'FPGA',
                                           'fpga_settings': {'timeout_run': 1, 'timeout_tune': 1}})


def test_run_thread_stops_the_box_after_a_read_error_then_closes():
    from gui.tabs.run_tab import RunThread
    thread = RunThread(types.SimpleNamespace(abort_now=False), run_config())
    fake = FakeDAQ()
    thread.daq = fake
    thread.execute()
    thread.cleanup()
    assert fake.calls == ['start', 'abort', 'stop', 'close']


def test_tune_thread_stops_the_box_then_closes(monkeypatch):
    import gui.tabs.tune_tab as tune_mod
    fake = FakeDAQ()
    monkeypatch.setattr(tune_mod, 'DAQConnection', lambda *a, **k: fake)
    thread = tune_mod.TuneThread(types.SimpleNamespace(running=True, dac_v=0, dac_c=0), run_config())
    thread.execute()
    assert fake.calls == ['start', 'abort', 'close']
