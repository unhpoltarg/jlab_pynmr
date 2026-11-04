"""Settings for the quadrature feature, read from unh/quadrature/quadrature.yaml.

The layout matches unh/data_streamer.yaml: top-level keys, then optional ``profiles: {<-p name>: {...}}``
overrides. Unknown keys are ignored with a log line. A missing or broken file gives the defaults, which
leave the feature off.
"""
import copy
import logging
import os

import yaml

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'quadrature.yaml')

# Nominal reference angles (deg) a sequence may use, and the name recorded for common sequences
ANGLES = (0, 90, 180, 270)
SEQUENCES = {
    'pair': [0, 90],
    'abba': [0, 90, 90, 0],
    'cycle4': [0, 90, 180, 270],
}

DEFAULTS = {
    'enable': False,          # False: no quadrature controls, PyNMR behaves exactly as without this feature
    'sequence': 'pair',       # a name from SEQUENCES, or a list of nominal angles, e.g. [0, 0, 0, 90]
    'settle_ms': 1.0,         # wait after each phase-DAC write before sweeps start, ms (original 1 ms guard)
    'cal': {
        'v_min': 0.0,         # lowest phase-DAC value stepped (0..1)
        'v_max': 0.94,        # highest phase-DAC value stepped (0..1); 0.94 x ~16 V = 15 V, the SCPHS-51+ rated top
        'steps': 21,          # grid points per pass
        'passes': 2,          # 1 = up only; 2 = up then down (shows hysteresis and drift)
        'sweeps_per_step': 64,    # sweeps averaged at each step; rounded up to a multiple of tune_per_chunk
        'ref_every': 10,      # return to the Real tune every this many steps to track drift (0 = never)
        'settle_ms': 1.0,     # wait after each calibration step's DAC write, ms
        'settle_test_chunks': 4,  # back-to-back chunks recorded after the settle-test jump (0 = skip)
        'gain_order': 2,      # polynomial order in v of the detector gain change (0 = constant gain)
        'offset_order': 1,    # polynomial order in v of the detector offset change (0 = constant)
        'fit_drift': True,    # fit a linear signal drift with time
        'bins': 16,           # frequency bins the sweep is averaged into for the fit
        'out_dir': 'quad_cal',  # calibration files go to <event_dir>/<out_dir>/
    },
    'default_tunes': None,    # {angle: phase DAC 0..1} used when the session has no usable set (read whole)
    'dispersion': {           # background subtraction for 90/270 deg records (unh/quadrature/dispersion.py)
        'joint_kk': True,     # polynomial fitted jointly with KK(latest absorption); False = JLab's wing fit
        'order': 3,           # polynomial order
        'edge': 3,            # points left out at each end of the sweep (edge effects of the transform)
    },
    'autotune': {             # Tune-tab Auto Tune (unh/quadrature/autotune.py); its records also go to cal out_dir
        'offsets': [-0.03, -0.015, 0.0, 0.015, 0.03],  # phase-DAC steps around each tune per pass (0..1)
        'sweeps_per_step': 64,    # rounded up to a multiple of tune_per_chunk
        'max_passes': 3,      # another pass, centred on the new tunes, while a target lies outside its steps
        'polish': True,       # then one tighter pass around the new tunes, which gives the final answer
        'polish_offsets': [-0.01, -0.005, 0.0, 0.005, 0.01],
        'settle_ms': 1.0,     # wait after each DAC write, ms
        'bins': 32,           # frequency bins for the fits
        'gain_order': 1,      # detector gain change with v, polynomial order (local scans: keep it low)
        'offset_order': 1,    # detector offset change with v, polynomial order
        'fit_drift': True,
        'mask_khz': [],       # frequency ranges left out of the trace fit, kHz from the centre, e.g. [[-60, 60]]
    },
}

log = logging.getLogger('PyNMR.unh.quadrature')


def _merge(cfg, data, where):
    for key, value in data.items():
        if key not in cfg:
            log.warning(f"Quadrature settings: ignoring unknown key {where}{key}.")
        elif isinstance(cfg[key], dict):
            if isinstance(value, dict):
                _merge(cfg[key], value, f'{where}{key}.')
            else:
                log.warning(f"Quadrature settings: {where}{key} must be a mapping; ignored.")
        else:
            cfg[key] = value


def sequence_of(cfg):
    """The configured sequence as a list of nominal angles (deg).

    Raises:
        ValueError: unknown name, empty list, or an angle not in ANGLES
    """
    seq = cfg['sequence']
    if isinstance(seq, str):
        if seq not in SEQUENCES:
            raise ValueError(f"unknown sequence {seq!r} (known: {', '.join(SEQUENCES)})")
        seq = SEQUENCES[seq]
    seq = [int(a) for a in seq]
    if not seq or any(a not in ANGLES for a in seq):
        raise ValueError(f"sequence must be a non-empty list of angles from {ANGLES}, got {seq}")
    if 0 not in seq:
        raise ValueError("sequence must include 0 (the Real tune)")
    return seq


def sequence_name(seq):
    """Name recorded as quad_mode: the SEQUENCES name if it matches one, else 'custom'."""
    for name, angles in SEQUENCES.items():
        if list(seq) == angles:
            return name
    return 'custom'


def load_settings(profile=None, path=CONFIG_FILE):
    """Read the quadrature settings, with the active profile's overrides applied.

    Args:
        profile: name of the -p profile in use, or None
        path: settings file

    Returns:
        dict of settings; the defaults (feature off) if the file is missing or invalid
    """
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return cfg
    except Exception as e:
        log.error(f"Quadrature disabled: could not read {path}: {e}")
        return cfg
    if not isinstance(data, dict):
        log.error(f"Quadrature disabled: {path} is not a mapping.")
        return cfg
    profiles = data.pop('profiles', None) or {}
    _merge(cfg, data, '')
    if profile and isinstance(profiles.get(profile), dict):
        _merge(cfg, profiles[profile], f'profiles.{profile}.')
    try:
        sequence_of(cfg)
        cfg['settle_ms'] = float(cfg['settle_ms'])
        if cfg['settle_ms'] < 0:
            raise ValueError('settle_ms must be >= 0')
        c = cfg['cal']
        if not (0.0 <= float(c['v_min']) < float(c['v_max']) <= 1.0):
            raise ValueError('cal needs 0 <= v_min < v_max <= 1')
        if int(c['steps']) < 5 or int(c['passes']) not in (1, 2) or int(c['gain_order']) < 0                 or int(c['offset_order']) < 0:
            raise ValueError('cal needs steps >= 5, passes 1 or 2, gain_order and offset_order >= 0')
        d = {int(k): float(v) for k, v in (cfg['default_tunes'] or {}).items()}
        if any(k not in ANGLES or not 0.0 <= v <= 1.0 for k, v in d.items()) or (d and 0 not in d):
            raise ValueError('default_tunes needs angles from 0/90/180/270 (including 0) and values 0..1')
        cfg['default_tunes'] = d
        a = cfg['autotune']
        offsets = [float(d) for d in a['offsets']]
        polish = [float(d) for d in a['polish_offsets']]
        if (len(offsets) < 3 or 0.0 not in offsets or len(polish) < 3 or 0.0 not in polish
                or int(a['max_passes']) < 1 or int(a['bins']) < 8):
            raise ValueError('autotune needs at least 3 offsets and polish_offsets, each including 0, '
                             'max_passes >= 1 and bins >= 8')
        a['offsets'], a['polish_offsets'] = offsets, polish
    except (ValueError, TypeError, KeyError) as e:
        log.error(f"Quadrature disabled: bad setting in {path}: {e}")
        cfg['enable'] = False
    return cfg
