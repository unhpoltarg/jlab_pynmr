"""Analysis-tab result options "Optimized McClellan Fits (Equilibrium)" and "(ssRF)" (feature ``mcclellan-fit``).

They run the online fitter's own fits inside PyNMR: the FitEngine of LabView-NMR-Fitter (online_fitter/engine.py,
which carries the optimized-mcclellan-fits routines), imported from the sibling folder, not copied. Each line goes
in exactly as the data streamer would send it (same signal, same amplitude_scale, the axis rebuilt from centre and
span by the fitter's own protocol code), so PyNMR and the online fitter fit the same numbers the same way.

- Equilibrium: the fast fit. r and the phase float, a cubic background is profiled out, and every lineshape
  constant, including the amplitude scale, is held fixed. P = (r^2 - 1)/(r^2 + r + 1) (ratio method).
  The constants start from the material preset, which rarely matches the data: press **Update Constants** once
  some equilibrium lines are in (the full open fit on the average of the last 10), as in the fitter. The result
  is saved and reloaded at the next start for the same material.
- ssRF: the fitter's hole-burnt fit (differential binning against the Update-Constants reference); it needs
  Update Constants first.

Both options share one engine, so they share the material, the constants and the equilibrium buffer. In
quadrature, only 0 deg records are fitted (and buffered); other angles are skipped.

Settings: unh/mcclellan.yaml (fitter_path, material). Signal, amplitude_scale and line_sign come from
data_streamer.yaml: at the true 0 deg positive P is a dip, and line_sign -1 turns it upward for the fitter's model.
"""
import json
import logging
import os
import sys
import threading

import numpy as np
import pyqtgraph as pg
import yaml
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QPushButton, QVBoxLayout

from gui.tabs.analysis_modules import AnalysisModule

log = logging.getLogger('PyNMR.unh.mcclellan')

UNH_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(UNH_DIR)
CONFIG_FILE = os.path.join(UNH_DIR, 'mcclellan.yaml')
DEFAULTS = {
    'fitter_path': '../LabView-NMR-Fitter',   # relative to the PyNMR folder, or absolute
    'material': 'ND3',                        # ND3, d-butanol or d-propanediol (the fitter's names)
}


def load_settings(profile=None, path=CONFIG_FILE):
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return cfg
    except Exception as e:
        log.error(f'McClellan fits: could not read {path}: {e}')
        return cfg
    profiles = data.pop('profiles', None) or {}
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    if profile and isinstance(profiles.get(profile), dict):
        cfg.update({k: v for k, v in profiles[profile].items() if k in DEFAULTS})
    return cfg


def fitter_root(cfg):
    p = os.path.expanduser(str(cfg['fitter_path']))
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(REPO, p))


def import_fitter(root):
    """(engine module, protocol module) from the online fitter at ``root``. Raises ImportError if absent."""
    if not os.path.isfile(os.path.join(root, 'online_fitter', 'engine.py')):
        raise ImportError(f'online fitter not found at {root}')
    if root not in sys.path:
        sys.path.insert(0, root)
    from online_fitter import engine, protocol
    return engine, protocol


def fitter_sweep(event, stream_cfg, protocol):
    """(freqs, signal, scale): the line exactly as the online fitter receives it from the streamer."""
    from unh.data_streamer import _arr, axis_params, line_scale
    freqs = np.asarray(event.scan.freq_list, dtype=float)
    centfreq, span, _uniform = axis_params(freqs)
    scale = line_scale(stream_cfg)                     # amplitude_scale x line_sign, as the streamer sends it
    sig = _arr(getattr(event, stream_cfg.get('signal', 'fitsub')), scale)
    msg = {'centfreq_mhz': centfreq, 'span_mhz': span, 'npts': len(freqs),
           'raw': _arr(event.scan.phase, scale), 'baseline_sub': sig}
    f, _raw, base = protocol.sweep_arrays(msg)
    return f, base, scale, span, centfreq


def fit_event(engine, protocol, event, mode, stream_cfg):
    """Fit one finished event with the fitter's ``mode`` ('equilibrium' or 'ssRF').

    Returns:
        dict: P (fraction, nan if none), curve (on the event's axis, PyNMR units, cubic included so it lies on
        the data), r, out (the engine's result dict), skipped (reason or None)
    """
    if getattr(event, 'quad_ref_deg', None) not in (None, 0):
        return {'P': float('nan'), 'curve': None, 'r': float('nan'), 'out': None,
                'skipped': f"{event.quad_ref_deg} deg quadrature record: only 0 deg records are fitted"}
    freqs, sig, scale, span, centfreq = fitter_sweep(event, stream_cfg, protocol)
    out = engine.fit_line(freqs, sig, mode, span=span, centfreq=centfreq)
    fit = np.asarray(out.get('fit'), dtype=float)
    flat = np.asarray(out.get('flat'), dtype=float)
    curve = None
    if fit.shape == sig.shape and flat.shape == sig.shape and np.all(np.isfinite(fit)):
        curve = (fit + (sig - flat)) / (scale or 1.0)       # model plus the fitter's own background
    P = out.get('P_fit', float('nan'))
    return {'P': float(P) / 100.0 if P is not None and np.isfinite(P) else float('nan'),
            'curve': curve, 'r': out.get('r', float('nan')), 'out': out, 'skipped': None}


class _Shared:
    """The one FitEngine both options use, its settings, and the saved-constants file."""

    def __init__(self, main_window):
        self.mw = main_window
        profile = getattr(main_window, 'profile', None)
        self.cfg = load_settings(profile)
        from unh.data_streamer import load_stream_config
        self.stream_cfg = load_stream_config(profile)
        self.root = fitter_root(self.cfg)
        self.engine = self.protocol = self.error = None
        self.material_names = ('ND3', 'd-butanol', 'd-propanediol')
        try:
            engine_mod, self.protocol = import_fitter(self.root)
            self.material_names = tuple(engine_mod.MATERIAL_NAMES)
            self.engine = engine_mod.FitEngine(material=self.cfg['material'])
            self.buffer = engine_mod.EQ_BUFFER_DEFAULT
        except Exception as e:
            self.error = f'{e}'
            self.buffer = 10
            log.warning(f'McClellan fits unavailable: {e}')
        self.busy = False
        self.panels = []
        if self.engine is not None:
            self.load_saved()

    def const_dir(self):
        return os.path.join(self.mw.config.settings['event_dir'], 'mcclellan')

    def const_file(self, material):
        return os.path.join(self.const_dir(), f'constants_{material}.json')

    def load_saved(self):
        path = self.const_file(self.engine.material)
        if not os.path.isfile(path):
            return
        try:
            with open(path) as f:
                self.engine.import_constants(json.load(f))
            log.info(f'McClellan fits: constants loaded from {path}.')
        except Exception as e:
            log.warning(f'McClellan fits: could not load {path}: {e}')

    def save(self):
        payload = self.engine.export_constants()
        if payload is None:
            return None
        os.makedirs(self.const_dir(), exist_ok=True)
        path = self.const_file(self.engine.material)
        with open(path, 'w') as f:
            json.dump(payload, f)
        return path

    def status(self):
        if self.engine is None:
            return (f'<span style="color:#d00000">The online fitter was not found ({self.error}). Set fitter_path '
                    f'in unh/mcclellan.yaml.</span>')
        s = self.engine.status()
        src = {'preset': 'material preset', 'fit': 'Update Constants', 'imported': 'saved Update Constants'}.get(
            s['const_source'], s['const_source'])
        cc = '' if s['CC'] is None else f", CC {s['CC']:.4g}"
        text = (f"Material {s['material']} ({s['model']} model). Constants from {src}{cc}. "
                f"{s['n_eq_buffered']}/{self.buffer} equilibrium lines buffered.")
        if self.busy:
            text += ' Update Constants running (a few seconds)...'
        if s['const_source'] == 'preset':
            return (f'<span style="color:#d00000">{text} The fast fit holds the preset constants fixed, so P '
                    f'is not trustworthy yet: press Update Constants once some equilibrium lines are in.</span>')
        return text

    def refresh(self):
        text = self.status()
        for p in self.panels:
            p.status_ready.emit(text)

    def update_constants(self):
        if self.engine is None or self.busy:
            return
        self.busy = True
        self.refresh()

        def work():
            try:
                res = self.engine.update_constants()
                path = self.save()
                msg = (f"Update Constants: P {res['P']:.2f} %, r {res['r']:.4f}, CC {res['CC']:.4g}, "
                       f"red. chi2 {res['red_chisq']:.3g}, from {res['n_avg']} lines."
                       + (f' Saved {path}.' if path else ''))
                log.info('McClellan fits: ' + msg)
            except Exception as e:
                msg = f'<span style="color:#d00000">Update Constants failed: {e}</span>'
                log.warning(f'McClellan fits: Update Constants failed: {e}')
            self.busy = False
            for p in self.panels:
                p.set_message(msg)
            self.refresh()

        threading.Thread(target=work, name='mcclellan_update_constants', daemon=True).start()

    def set_material(self, name):
        if self.engine is None or name == self.engine.material:
            return
        self.engine.set_material(name)
        self.load_saved()
        for p in self.panels:
            p.show_material(name)
        self.refresh()


_SHARED = {}


def shared(main_window):
    key = id(main_window)
    if key not in _SHARED:
        _SHARED[key] = _Shared(main_window)
    return _SHARED[key]


class McClellanResult(AnalysisModule):
    """One result option; ``mode`` is the fitter's mode ('equilibrium' or 'ssRF')."""
    status_ready = Signal(str)

    def __init__(self, parent, mode, title):
        super().__init__(parent)
        self.parent = parent
        self.mode = mode
        self.name = title
        self.sh = shared(parent.parent)
        self.sh.panels.append(self)
        self.space = QVBoxLayout()
        self.setLayout(self.space)
        grid = QGridLayout()
        self.space.addLayout(grid)
        grid.addWidget(QLabel('Material:'), 0, 0)
        self.material = QComboBox()
        self.material.addItems(list(self.sh.material_names))
        if self.sh.engine is not None:
            self.material.setCurrentText(self.sh.engine.material)
        self.material.currentTextChanged.connect(self.sh.set_material)
        grid.addWidget(self.material, 0, 1)
        self.update_button = QPushButton('Update Constants')
        self.update_button.setToolTip('Full open fit on the average of the last equilibrium lines (as the online '
                                      'fitter does): refreshes every lineshape constant, the amplitude scale and '
                                      'CC. Run it on a clean equilibrium plateau.')
        self.update_button.clicked.connect(self.sh.update_constants)
        grid.addWidget(self.update_button, 0, 2)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.space.addWidget(self.status)
        self.message = QLabel('')
        self.message.setWordWrap(True)
        self.space.addWidget(self.message)
        self.space.addStretch(1)
        self.status_ready.connect(self.status.setText)
        self.update_button.setEnabled(self.sh.engine is not None)
        self.material.setEnabled(self.sh.engine is not None)
        self.status.setText(self.sh.status())

    @Slot(str)
    def show_material(self, name):
        self.material.blockSignals(True)
        self.material.setCurrentText(name)
        self.material.blockSignals(False)

    def switch_here(self):
        self.parent.res_region.setBrush(pg.mkBrush(0, 0, 180, 0))

    def result(self, event_data):
        """AnalThread: (result curve, area, polarization). The area slot keeps PyNMR's own sum of Fit Subtracted."""
        sweep = np.asarray(event_data.fitsub, dtype=float)
        area = float(sweep.sum())
        zeros = np.zeros(len(sweep))
        if self.sh.engine is None:
            self.set_message('No fit: the online fitter was not found.')
            return zeros, area, float('nan')
        try:
            res = fit_event(self.sh.engine, self.sh.protocol, event_data, self.mode, self.sh.stream_cfg)
        except Exception as e:
            self.set_message(f'Fit failed: {e}')
            return zeros, area, float('nan')
        if res['skipped']:
            self.set_message(f"Not fitted: {res['skipped']}.")
            return zeros, area, float('nan')
        out = res['out']
        parts = [f"P {100 * res['P']:.2f} %" if np.isfinite(res['P']) else 'P not available',
                 f"r {out.get('r', float('nan')):.4f}"]
        if out.get('phase_deg') is not None:
            parts.append(f"phase {out['phase_deg']:.1f} deg")
        if out.get('red_chisq') is not None:
            parts.append(f"red. chi2 {out['red_chisq']:.3g}")
        if out.get('P_area') is not None and np.isfinite(out['P_area']):
            parts.append(f"area-method P {out['P_area']:.2f} %")
        text = ', '.join(parts) + '.'
        for key in ('warning', 'error'):
            if out.get(key):
                text += f'<br><span style="color:#d00000">{out[key]}</span>'
        self.set_message(text)
        self.sh.refresh()
        curve = res['curve'] if res['curve'] is not None else zeros
        return curve, area, res['P']


def mcclellan_result_options(anal_tab):
    """The two result options, for AnalysisTab._init_result_options."""
    return [McClellanResult(anal_tab, 'equilibrium', 'Optimized McClellan Fits (Equilibrium)'),
            McClellanResult(anal_tab, 'ssRF', 'Optimized McClellan Fits (ssRF)')]
