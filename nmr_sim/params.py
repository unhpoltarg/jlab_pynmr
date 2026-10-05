"""Defaults and validation for the ``nmr_sim`` configuration dict.

The dict normally comes from ``settings: nmr_sim:`` of a PyNMR profile.
``resolve`` never mutates its input (PyNMR writes the settings dict into every
event file) and rejects unknown keys so typos fail loudly.
"""

import copy
from dataclasses import asdict

from .qmeter import QMeterParams

DEFAULTS = {
    "seed": None,               # int, or None = fresh entropy (printed and logged)
    "speed": 60.0,              # simulated seconds per wall-clock second
    "start_at_s": 0.0,          # simulated time at start, s (skip into the timeline)
    "sweep_time_s": 0.005,      # wall-clock sleep per sweep in get_chunk, s
    "field_T": None,            # magnet field, T (None = on resonance at tune freq)
    "te_temp_K": 1.0,           # lattice temperature for P_TE, K
    "material": "deuterated ammonia (Dec 2024)",  # preset name or constants dict
    "calibration": {
        "P": 0.0019,            # polarization (fraction) at which ...
        "peak_phase_V": 8.0e-4,  # ... the phase signal peak height is this, V
    },
    "qmeter": asdict(QMeterParams()),
    "noise": {
        "sigma_phase_V": 1.5e-3,     # per-sweep phase noise, V
        "sigma_diode_V": 1.0e-3,     # per-sweep diode noise, V
        "drift_amp_V": 0.0,          # sinusoidal phase-offset drift amplitude, V
        "drift_period_s": 3600.0,    # drift period, simulated s
        "drift_rate_V_per_h": 0.0,   # linear phase-offset drift, V / simulated h
    },
    "truth_log_dir": "log",     # directory for the truth CSV (None = no log)
    "timeline": [
        {"name": "baseline", "kind": "hold", "P": "te", "duration_s": 7200.0,
         "line_offset_MHz": 1.2},
        {"name": "te", "kind": "hold", "P": "te", "duration_s": 3600.0},
        {"name": "spinup", "kind": "spinup", "P_inf": 0.40, "tau_s": 3600.0,
         "duration_s": 21600.0},
        {"name": "relax", "kind": "relax", "T1_s": 10800.0, "duration_s": None},
    ],
}

# Keys whose values are replaced whole rather than merged key by key.
_LEAF_KEYS = {"material", "timeline"}


def resolve(user_cfg):
    """Return a new, fully populated config: DEFAULTS deep-merged with user_cfg.

    Raises ValueError on unknown keys (top level and inside the nested
    ``calibration``, ``qmeter`` and ``noise`` blocks).
    """
    cfg = copy.deepcopy(DEFAULTS)
    for key, val in (user_cfg or {}).items():
        if key not in DEFAULTS:
            raise ValueError(f"nmr_sim: unknown key {key!r}")
        if isinstance(DEFAULTS[key], dict) and key not in _LEAF_KEYS:
            if not isinstance(val, dict):
                raise ValueError(f"nmr_sim: {key} must be a mapping")
            unknown = set(val) - set(DEFAULTS[key])
            if unknown:
                raise ValueError(f"nmr_sim.{key}: unknown keys {sorted(unknown)}")
            cfg[key].update(copy.deepcopy(val))
        else:
            cfg[key] = copy.deepcopy(val)
    return cfg
