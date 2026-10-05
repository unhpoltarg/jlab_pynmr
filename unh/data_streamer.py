"""UNH only: stream each finished event's processed NMR line to LabView-NMR-Fitter.

The fitter (github.com/unhpoltarg/LabView-NMR-Fitter, online_fitter/) listens on a loopback TCP socket for
line-delimited JSON "sweep" messages, the same ones the legacy UNH LabVIEW VI sends, and replies with one
JSON line per sweep. This module makes PyNMR a second client of that socket.

It is self-contained: the only hook in shared code is a tagged block in MainWindow.__init__ that calls
attach_streamer(). Settings live in unh/data_streamer.yaml. See unh/README.md for how to enable or remove it.
"""
import copy
import json
import logging
import os
import queue
import socket

import numpy as np
import yaml

from core import EventType
from core.thread_manager import BaseThread, get_thread_manager

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_streamer.yaml')

DEFAULTS = {
    'enable': False,
    'host': '127.0.0.1',
    'port': 8777,
    'signal': 'fitsub',          # event attribute sent as the fitter's baseline_sub: fitsub or basesub
    'amplitude_scale': 1.0,      # multiplies raw and signal before sending
    'connect_timeout': 1.0,      # s
    'reply_timeout': 5.0,        # s
    'species': ['deuteron'],     # stream only channels of these species; empty list streams all
}
SIGNALS = ('fitsub', 'basesub')
QUEUE_SIZE = 5
UNIFORM_TOL = 0.05               # max step spread, as a fraction of the mean step, for a uniform axis
                                 # (int32 truncation of the sweep table alone gives up to ~2 of ~128 units)

log = logging.getLogger('PyNMR.unh.data_streamer')


def load_stream_config(profile=None, path=CONFIG_FILE):
    """Read streamer settings, with the override for the active profile applied.

    Args:
        profile: Name of the -p profile in use, or None
        path: Settings file

    Returns:
        Dict of settings. Defaults (streaming disabled) if the file is missing or invalid.
    """
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return cfg
    except Exception as e:
        log.error(f"Data streamer disabled: could not read {path}: {e}")
        return cfg
    if not isinstance(data, dict):
        log.error(f"Data streamer disabled: {path} is not a mapping.")
        return cfg
    profiles = data.pop('profiles', None) or {}
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    if profile and isinstance(profiles.get(profile), dict):
        cfg.update({k: v for k, v in profiles[profile].items() if k in DEFAULTS})
    if cfg['signal'] not in SIGNALS:
        log.error(f"Data streamer disabled: signal must be one of {SIGNALS}, got {cfg['signal']!r}.")
        cfg['enable'] = False
    return cfg


def labview_timestamp(dt):
    """Format a datetime as local time the way LabVIEW does, e.g. '6/17/2026 9:31:27 PM'.

    Built by hand because Windows strftime has no %-m / %-d / %-I.
    """
    t = dt.astimezone() if dt.tzinfo else dt
    hour = t.hour % 12 or 12
    return f"{t.month}/{t.day}/{t.year} {hour}:{t.minute:02d}:{t.second:02d} {'AM' if t.hour < 12 else 'PM'}"


def axis_params(freqs):
    """Centre and span (MHz) such that the fitter's axis, centfreq + span*(arange(n)/n - 0.5), reproduces freqs.

    Args:
        freqs: Frequency list in MHz, ascending

    Returns:
        (centfreq, span, uniform): uniform is False if the steps vary by more than UNIFORM_TOL
    """
    f = np.asarray(freqs, dtype=float)
    n = len(f)
    step = (f[-1] - f[0]) / (n - 1)
    span = step * n
    centfreq = f[0] + span / 2
    steps = np.diff(f)
    uniform = bool(step > 0 and np.ptp(steps) <= UNIFORM_TOL * step)
    return centfreq, span, uniform


def _num(x):
    """JSON-safe float: None for missing or non-finite values."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _arr(a, scale=1.0):
    return (np.asarray(a, dtype=float) * scale).tolist()


def build_sweep_message(event, cfg):
    """Build the fitter's sweep message for one finished event.

    Everything comes from the event itself (its own Config and scan), never from MainWindow.config, so a
    window or channel change made after the event started can't leak into it.

    Args:
        event: Finished, analysed EventData
        cfg: Streamer settings from load_stream_config

    Returns:
        Dict for the fitter's protocol: type, ts, centfreq_mhz, span_mhz, npts, raw, baseline_sub,
        plus extra fields the fitter ignores today (source, freqs_mhz, basesub, fitsub, ...).
    """
    freqs = np.asarray(event.scan.freq_list, dtype=float)
    centfreq, span, uniform = axis_params(freqs)
    scale = float(cfg.get('amplitude_scale', 1.0))
    channel = event.config.channel
    return {
        'type': 'sweep',
        'ts': labview_timestamp(event.stop_time),
        'centfreq_mhz': centfreq,
        'span_mhz': span,
        'npts': len(freqs),
        'raw': _arr(event.scan.phase, scale),
        'baseline_sub': _arr(getattr(event, cfg.get('signal', 'fitsub')), scale),
        'source': 'pynmr',
        'uniform_axis': uniform,
        'freqs_mhz': freqs.tolist(),
        'basesub': _arr(event.basesub, scale),
        'fitsub': _arr(event.fitsub, scale),
        'amplitude_scale': scale,
        'channel': channel.get('name'),
        'cent_freq_mhz': _num(channel.get('cent_freq')),
        'mod_freq_khz': _num(channel.get('mod_freq')),
        'sweeps': int(event.scan.num),
        'pynmr_area': _num(event.area),
        'pynmr_pol': _num(event.pol),
        'pynmr_cc': _num(event.cc),
        'stop_stamp': _num(event.stop_stamp),
    }


def encode_message(msg):
    """One CRLF-terminated JSON line, as the fitter's protocol expects."""
    return (json.dumps(msg) + '\r\n').encode('utf-8')


class DataStreamer(BaseThread):
    """Sends finished events to the fitter from a worker thread, so the GUI never waits on the network.

    Messages are built on the GUI thread when the event finishes and handed over through a small queue; if the
    fitter is slow or down, the oldest waiting message is dropped. Each reply is emitted on `reply`.

    Args:
        cfg: Streamer settings from load_stream_config
    """

    def __init__(self, cfg):
        super().__init__(name='unh_data_streamer', parent=None)
        self.cfg = cfg
        self.queue = queue.Queue(maxsize=QUEUE_SIZE)
        self.sock = None
        self.reader = None
        self.link_down = False          # True after a failure has been logged, until a send succeeds
        self.warned = set()             # one-time warnings already logged

    def warn_once(self, key, message):
        if key not in self.warned:
            self.warned.add(key)
            log.warning(message)

    def wants(self, event):
        """True if this event's channel species is one we stream"""
        species = self.cfg.get('species') or []
        if not species:
            return True
        channel = event.config.channel
        if channel.get('species') in species:
            return True
        self.warn_once(('species', channel.get('name')),
                       f"Data streamer: not streaming channel {channel.get('name')} "
                       f"(species {channel.get('species')!r} not in {species}).")
        return False

    def on_event_finished(self, bus_data):
        """Event bus handler for EVENT_FINISHED (runs on the GUI thread)"""
        event = bus_data.get('event')
        if event is not None and self.wants(event):
            self.submit(event)

    def submit(self, event):
        """Build the message for a finished event and queue it for sending, dropping the oldest if full"""
        msg = build_sweep_message(event, self.cfg)
        if not msg['uniform_axis']:
            self.warn_once('uniform', "Data streamer: this sweep's frequency axis is not uniform. The fitter rebuilds "
                                      "its axis from centfreq/span unless it supports freqs_mhz.")
        while True:
            try:
                self.queue.put_nowait(msg)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    log.warning("Data streamer: fitter not keeping up, dropped oldest queued event.")
                except queue.Empty:
                    pass

    def execute(self):
        log.info(f"Data streamer sending to {self.cfg['host']}:{self.cfg['port']}.")
        while not self.should_stop():
            try:
                msg = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            reply = self.send_one(msg)
            if reply is not None:
                self.emit_reply(reply)

    def cleanup(self):
        self.close()

    def stop_thread(self, timeout=5000):
        """Stop, first shutting the socket so a send or reply wait in progress returns at once"""
        self._is_stopping = True
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return super().stop_thread(timeout)

    def send_one(self, msg):
        """Send one message and wait for its reply line.

        Returns:
            Reply dict, or None if the fitter could not be reached or replied with something unreadable.
            Never raises.
        """
        try:
            if self.sock is None:
                self.sock = socket.create_connection((self.cfg['host'], int(self.cfg['port'])),
                                                     timeout=float(self.cfg['connect_timeout']))
                self.reader = self.sock.makefile('rb')
            self.sock.settimeout(float(self.cfg['reply_timeout']))
            self.sock.sendall(encode_message(msg))
            line = self.reader.readline()
            if not line:
                raise ConnectionError('fitter closed the connection')
        except (OSError, ValueError) as e:
            self.close()
            if self.should_stop():
                return None
            if not self.link_down:
                log.warning(f"Data streamer: fitter at {self.cfg['host']}:{self.cfg['port']} unavailable ({e}); "
                            f"will retry with each event.")
                self.link_down = True
            return None
        if self.link_down:
            log.info("Data streamer: fitter connection restored.")
            self.link_down = False
        try:
            return json.loads(line)
        except ValueError:
            log.warning(f"Data streamer: unreadable reply from fitter: {line[:200]!r}")
            return None

    def close(self):
        for f in (self.reader, self.sock):
            try:
                if f is not None:
                    f.close()
            except OSError:
                pass
        self.reader = None
        self.sock = None


def show_reply(main_window, reply):
    """Log the fitter's reply and show it in the status bar. Nothing is written to the eventfile, history or EPICS."""
    if reply.get('ok'):
        p = reply.get('P_fit')
        mes = f"Fitter ({reply.get('fit_type')}): P_fit = {p if p is not None else 'n/a'} %, P_area = {reply.get('P_area')} %"
        if reply.get('warning'):
            mes += f" (warning: {reply['warning']})"
    else:
        mes = f"Fitter error: {reply.get('error')}"
    log.info(mes)
    status_bar = getattr(main_window, 'status_bar', None)
    if status_bar is not None:
        status_bar.showMessage(mes)


def attach_streamer(main_window):
    """Start streaming finished events to the fitter, if enabled in data_streamer.yaml for this profile.

    Called once from MainWindow.__init__. Never raises: a broken streamer only logs an error.

    Returns:
        The running DataStreamer, or None
    """
    try:
        cfg = load_stream_config(getattr(main_window, 'profile', None))
        if not cfg['enable']:
            return None
        bus = getattr(main_window, 'event_bus', None)
        if bus is None:
            log.error("Data streamer not started: no event bus.")
            return None
        streamer = DataStreamer(cfg)
        get_thread_manager().register_thread(streamer)   # stopped by closeEvent's stop_all_threads
        main_window.register_thread(streamer)            # keep a reference
        streamer.reply.connect(lambda reply: show_reply(main_window, reply))
        bus.subscribe(EventType.EVENT_FINISHED, streamer.on_event_finished)
        streamer.start_thread()
        main_window.data_streamer = streamer
        return streamer
    except Exception as e:
        log.error(f"Data streamer not started: {e}")
        return None
