"""Tests for the UNH data streamer (unh/data_streamer.py): each finished event's processed NMR line sent to
LabView-NMR-Fitter's sweep socket.

Run from the repo root in the pynmr env:
    conda run -n pynmr --no-capture-output python -m pytest unh/tests
"""
import datetime
import json
import logging
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
import types

import numpy as np
import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication

from config import Config
from core import BusData, EventBus, EventType
from unh import data_streamer as ds

FITTER = os.path.abspath(os.path.join(REPO, '..', 'LabView-NMR-Fitter'))
SETTINGS = {'steps': 512}


def channel(cent=32.7, mod=400.0, species='deuteron', name='Deuteron5T', sweep_file='tri'):
    ch = {'name': name, 'cent_freq': cent, 'mod_freq': mod, 'power': 400.0, 'sweep_file': sweep_file}
    if species is not None:
        ch['species'] = species
    return ch


def fake_event(config=None, stamp=1.7e9):
    """Stand-in for a finished, analysed EventData carrying only what the streamer reads."""
    config = config or Config(channel(), SETTINGS)
    n = len(config.freq_list)
    x = np.linspace(-1, 1, n)
    stop_time = datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc)
    return types.SimpleNamespace(
        config=config,
        scan=types.SimpleNamespace(freq_list=config.freq_list, phase=0.5 + 0.1 * x + np.exp(-x**2 / 0.01), num=640),
        basesub=0.1 * x + np.exp(-x**2 / 0.01), fitsub=np.exp(-x**2 / 0.01),
        area=12.5, pol=-1.0, cc=-0.08, stop_time=stop_time, stop_stamp=stamp)


def cfg(**kw):
    c = dict(ds.DEFAULTS, enable=True)
    c.update(kw)
    return c


def fitter_axis(msg):
    """The fitter's own axis reconstruction (online_fitter/protocol.py freq_axis)"""
    n = int(msg['npts'])
    return msg['centfreq_mhz'] + msg['span_mhz'] * (np.arange(n) / n - 0.5)


@pytest.fixture(scope='module')
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


class FakeFitter:
    """Loopback server speaking the fitter's protocol: one JSON reply line per received line."""

    def __init__(self, reply=None, port=0):
        self.received = []
        outer = self
        reply = reply or {'ok': True, 'fit_type': 'equilibrium', 'P_area': 41.2, 'P_fit': 40.8, 'r': 1.73}

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for line in self.rfile:
                    outer.received.append(json.loads(line))
                    self.wfile.write((json.dumps(reply) + '\r\n').encode())

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(('127.0.0.1', port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


# --- Message ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('cent, mod', [(32.7, 400.0), (32.7, 200.0), (32.5, 800.0), (212.882, 150.0)])
def test_fitter_axis_reproduces_freq_list(cent, mod):
    """The fitter's centfreq + span*(arange(n)/n - 0.5) matches PyNMR's freq_list to within one sweep integer
    (mod_freq/32768, from the int32 truncation in Config), which is under 1% of a frequency step."""
    msg = ds.build_sweep_message(fake_event(Config(channel(cent, mod), SETTINGS)), cfg())
    assert msg['npts'] == 512
    one_int = mod / 1000 / 32768
    np.testing.assert_allclose(fitter_axis(msg), msg['freqs_mhz'], rtol=0, atol=one_int)
    assert one_int < 0.01 * msg['span_mhz'] / msg['npts']
    assert msg['uniform_axis'] is True


def test_message_has_fitter_fields_and_is_one_crlf_json_line():
    msg = ds.build_sweep_message(fake_event(), cfg())
    for key in ('type', 'ts', 'centfreq_mhz', 'span_mhz', 'npts', 'raw', 'baseline_sub'):
        assert key in msg
    assert msg['type'] == 'sweep' and msg['source'] == 'pynmr'
    assert msg['npts'] == len(msg['raw']) == len(msg['baseline_sub']) == len(msg['freqs_mhz'])
    line = ds.encode_message(msg)
    assert line.endswith(b'\r\n') and line.count(b'\n') == 1
    assert json.loads(line) == msg
    assert msg['sweeps'] == 640 and msg['pynmr_area'] == 12.5 and msg['channel'] == 'Deuteron5T'


def test_signal_choice_and_amplitude_scale():
    ev = fake_event()
    fit = ds.build_sweep_message(ev, cfg())
    np.testing.assert_allclose(fit['baseline_sub'], ev.fitsub)
    base = ds.build_sweep_message(ev, cfg(signal='basesub', amplitude_scale=2.0))
    np.testing.assert_allclose(base['baseline_sub'], 2.0 * ev.basesub)
    np.testing.assert_allclose(base['raw'], 2.0 * ev.scan.phase)
    np.testing.assert_allclose(base['fitsub'], 2.0 * ev.fitsub)


def test_non_finite_scalars_become_null():
    ev = fake_event()
    ev.pol = float('nan')
    msg = ds.build_sweep_message(ev, cfg())
    assert msg['pynmr_pol'] is None
    json.loads(ds.encode_message(msg))


@pytest.mark.parametrize('dt, text', [
    (datetime.datetime(2026, 6, 17, 21, 31, 27), '6/17/2026 9:31:27 PM'),
    (datetime.datetime(2026, 1, 5, 0, 4, 9), '1/5/2026 12:04:09 AM'),
    (datetime.datetime(2026, 12, 25, 12, 0, 0), '12/25/2026 12:00:00 PM'),
])
def test_labview_timestamp(dt, text):
    assert ds.labview_timestamp(dt) == text


def test_timestamp_is_local_time():
    utc = datetime.datetime(2026, 6, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)
    assert ds.labview_timestamp(utc) == ds.labview_timestamp(utc.astimezone().replace(tzinfo=None))


@pytest.mark.skipif(not os.path.isdir(FITTER), reason='LabView-NMR-Fitter not checked out next to this repo')
def test_fitter_protocol_decodes_message():
    """The fitter's own parser (online_fitter.protocol) accepts the message and gets PyNMR's axis and signal."""
    sys.path.insert(0, FITTER)
    try:
        from online_fitter import protocol
    finally:
        sys.path.remove(FITTER)
    ev = fake_event(Config(channel(32.7, 400.0), SETTINGS))
    msg = protocol.decode_message(ds.encode_message(ds.build_sweep_message(ev, cfg())).strip())
    freqs, raw, base = protocol.sweep_arrays(msg)
    np.testing.assert_allclose(freqs, ev.scan.freq_list, rtol=0, atol=0.400 / 32768)   # one sweep integer
    np.testing.assert_allclose(base, ev.fitsub)
    np.testing.assert_allclose(raw, ev.scan.phase)


# --- Window changes (unh_dev/interactive_freq_window) ------------------------------------------------------

def test_each_event_sent_with_its_own_window():
    """Two events started under different windows each carry their own axis, whatever the current window is."""
    first = fake_event(Config(channel(32.7, 400.0), SETTINGS))
    second = fake_event(Config(channel(32.5, 200.0), SETTINGS))
    m1, m2 = ds.build_sweep_message(first, cfg()), ds.build_sweep_message(second, cfg())
    assert m1['centfreq_mhz'] == pytest.approx(32.7, abs=1e-3) and m1['span_mhz'] == pytest.approx(0.8, abs=2e-3)
    assert m2['centfreq_mhz'] == pytest.approx(32.5, abs=1e-3) and m2['span_mhz'] == pytest.approx(0.4, abs=1e-3)
    assert (m1['cent_freq_mhz'], m1['mod_freq_khz']) == (32.7, 400.0)
    assert (m2['cent_freq_mhz'], m2['mod_freq_khz']) == (32.5, 200.0)
    np.testing.assert_allclose(m1['freqs_mhz'], first.scan.freq_list)


def test_non_uniform_sweep_file_sends_exact_axis_and_warns_once(tmp_path, caplog):
    ints = np.concatenate([np.linspace(-32768, -16384, 64), np.linspace(-16000, 32767, 448)]).astype(int)
    sweep = tmp_path / 'sweep.txt'
    np.savetxt(sweep, ints, fmt='%d')
    config = Config(channel(sweep_file=str(sweep)), SETTINGS)
    streamer = ds.DataStreamer(cfg())
    with caplog.at_level(logging.WARNING, logger=ds.log.name):
        streamer.submit(fake_event(config))
        streamer.submit(fake_event(config))
    msg = streamer.queue.get_nowait()
    assert msg['uniform_axis'] is False
    np.testing.assert_allclose(msg['freqs_mhz'], config.freq_list)
    assert sum('not uniform' in r.message for r in caplog.records) == 1


# --- Species filter ------------------------------------------------------------------------------------

def test_species_filter():
    streamer = ds.DataStreamer(cfg())
    for ch in (channel(species='proton', name='Proton5T'), channel(species=None, name='Legacy')):
        streamer.on_event_finished(BusData(EventType.EVENT_FINISHED, 'test', {'event': fake_event(Config(ch, SETTINGS))}))
    assert streamer.queue.empty()
    streamer.on_event_finished(BusData(EventType.EVENT_FINISHED, 'test', {'event': fake_event()}))
    assert streamer.queue.qsize() == 1
    everything = ds.DataStreamer(cfg(species=[]))
    everything.on_event_finished(BusData(EventType.EVENT_FINISHED, 'test',
                                         {'event': fake_event(Config(channel(species='proton'), SETTINGS))}))
    assert everything.queue.qsize() == 1


# --- Settings ------------------------------------------------------------------------------------------

def test_shipped_settings_keep_streaming_off():
    """The committed data_streamer.yaml must not switch streaming on for anyone by default."""
    for profile in (None, 'Test', 'Deuteron', 'Proton'):
        assert ds.load_stream_config(profile)['enable'] is False


def test_missing_or_invalid_settings_disable_streaming(tmp_path):
    assert ds.load_stream_config(path=str(tmp_path / 'absent.yaml')) == ds.DEFAULTS
    bad = tmp_path / 'bad.yaml'
    bad.write_text('enable: [unclosed\n')
    assert ds.load_stream_config(path=str(bad))['enable'] is False
    wrong = tmp_path / 'wrong.yaml'
    wrong.write_text('enable: True\nsignal: rescurve\n')
    assert ds.load_stream_config(path=str(wrong))['enable'] is False


def test_profile_override(tmp_path):
    f = tmp_path / 's.yaml'
    f.write_text('enable: False\nport: 9000\nprofiles:\n  Deuteron:\n    enable: True\n    signal: basesub\n')
    assert ds.load_stream_config('Proton', path=str(f))['enable'] is False
    d = ds.load_stream_config('Deuteron', path=str(f))
    assert d['enable'] is True and d['signal'] == 'basesub' and d['port'] == 9000


# --- Sending -------------------------------------------------------------------------------------------

def test_send_one_gets_reply_from_fitter():
    fitter = FakeFitter()
    try:
        streamer = ds.DataStreamer(cfg(port=fitter.port))
        reply = streamer.send_one(ds.build_sweep_message(fake_event(), streamer.cfg))
        assert reply['ok'] is True and reply['P_fit'] == 40.8
        reply = streamer.send_one(ds.build_sweep_message(fake_event(), streamer.cfg))   # same connection reused
        assert reply['ok'] is True
        assert len(fitter.received) == 2 and fitter.received[0]['npts'] == 512
        streamer.close()
    finally:
        fitter.close()


def test_fitter_down_logs_once_then_recovers(caplog):
    streamer = ds.DataStreamer(cfg(port=free_port(), connect_timeout=0.5))
    msg = ds.build_sweep_message(fake_event(), streamer.cfg)
    with caplog.at_level(logging.INFO, logger=ds.log.name):
        assert streamer.send_one(msg) is None
        assert streamer.send_one(msg) is None
        fitter = FakeFitter()
        try:
            streamer.cfg['port'] = fitter.port
            assert streamer.send_one(msg)['ok'] is True
        finally:
            streamer.close()
            fitter.close()
    assert sum('unavailable' in r.message for r in caplog.records) == 1
    assert sum('restored' in r.message for r in caplog.records) == 1


def test_full_queue_drops_oldest():
    streamer = ds.DataStreamer(cfg())
    for i in range(ds.QUEUE_SIZE + 2):
        streamer.submit(fake_event(stamp=1.7e9 + i))
    assert streamer.queue.qsize() == ds.QUEUE_SIZE
    assert streamer.queue.get_nowait()['stop_stamp'] == 1.7e9 + 2


# --- Hooking into PyNMR --------------------------------------------------------------------------------

class FakeMain:
    """Stand-in for MainWindow carrying only what attach_streamer uses."""

    def __init__(self, bus, profile='Test'):
        self.event_bus = bus
        self.profile = profile
        self.threads = []
        self.messages = []
        self.status_bar = types.SimpleNamespace(showMessage=self.messages.append)

    def register_thread(self, thread):
        self.threads.append(thread)


def test_attach_does_nothing_when_disabled(qapp, monkeypatch):
    bus = EventBus()
    main = FakeMain(bus)
    monkeypatch.setattr(ds, 'load_stream_config', lambda profile: dict(ds.DEFAULTS))
    assert ds.attach_streamer(main) is None
    assert main.threads == [] and not getattr(bus, '_handlers', {}).get(EventType.EVENT_FINISHED)


def test_attach_streams_finished_events_end_to_end(qapp, monkeypatch):
    """EVENT_FINISHED on the bus -> message at the fitter -> reply in the status bar; a bad event can't raise."""
    fitter = FakeFitter()
    bus = EventBus()
    main = FakeMain(bus)
    monkeypatch.setattr(ds, 'load_stream_config', lambda profile: cfg(port=fitter.port))
    streamer = ds.attach_streamer(main)
    try:
        assert streamer is not None and main.threads == [streamer] and main.data_streamer is streamer
        bus.publish(EventType.EVENT_FINISHED, 'main_window', {'event': object(), 'current_event': None})  # logged, not raised
        bus.publish(EventType.EVENT_FINISHED, 'main_window', {'event': fake_event(), 'current_event': None})
        deadline = time.time() + 5
        while not main.messages and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        assert len(fitter.received) == 1 and fitter.received[0]['source'] == 'pynmr'
        assert main.messages and 'P_fit = 40.8' in main.messages[-1]
    finally:
        assert streamer.stop_thread(timeout=3000) is True
        fitter.close()


def test_show_reply_error_text():
    main = FakeMain(None)
    ds.show_reply(main, {'ok': False, 'error': 'bad npts'})
    assert main.messages == ['Fitter error: bad npts']


# --- Isolation -----------------------------------------------------------------------------------------

def test_hook_block_tolerates_missing_unh_package(monkeypatch):
    """The data-streamer block in MainWindow.__init__ runs without error if unh/ has been deleted."""
    from unh.strip_unh import parse
    with open(os.path.join(REPO, 'gui', 'main_window.py'), encoding='utf-8') as f:
        lines = f.read().split('\n')
    hooks = [h for h in parse('\n'.join(lines)) if h['feature'] == 'data-streamer']
    assert len(hooks) == 1 and hooks[0]['kind'] == 'block'
    code = 'def init(self):\n' + '\n'.join(lines[hooks[0]['start']:hooks[0]['end'] + 1]) + '\n'
    monkeypatch.setitem(sys.modules, 'unh.data_streamer', None)   # import now raises ImportError
    namespace = {}
    exec(code, namespace)
    namespace['init'](object())


def test_tag_only_in_main_window_and_unh():
    out = subprocess.run(['git', 'grep', '-l', '--untracked', 'UNH-HOOK data-streamer'], cwd=REPO,
                         capture_output=True, text=True).stdout.split()
    assert 'gui/main_window.py' in out
    assert all(path in ('gui/main_window.py', 'changelog/changelog.md') or path.startswith('unh/') for path in out)
