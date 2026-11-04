"""Quadrature fields on event and baseline records, and the calibration files.

Event records: the quad_* fields are set as attributes on the EventData, and EventData.print_event writes
every attribute as a top-level key. The names avoid 'config' and 'scan', which print_event flattens.
Nothing is added while quadrature is off.

Calibration records: one JSON file per calibration in <event_dir>/<cal.out_dir>/<cal_id>.json. They are
kept out of the event files so that readers of those files are not affected.
"""
import glob
import json
import logging
import os

import numpy as np

log = logging.getLogger('PyNMR.unh.quadrature')

CAL_SCHEMA = 1


def tag_event(event, tags):
    """Set the quad_* fields on an event (no-op for empty tags)."""
    for key, value in (tags or {}).items():
        setattr(event, key, value)


def angle_of(record):
    """Nominal reference angle (deg) of an event or baseline record (dict or object); 0 if untagged."""
    if isinstance(record, dict):
        value = record.get('quad_ref_deg')
    else:
        value = getattr(record, 'quad_ref_deg', None)
    return 0 if value is None else int(value)


def is_real(record):
    """True for records that are polarizations: untagged, or taken at the Real (0 deg) tune."""
    return angle_of(record) == 0


def same_vout(a, b, tol=1e-4):
    """True if two phase-DAC values are the same setting (both None counts as the same)."""
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def group_baselines(events, stamps):
    """Average selected Baseline-tab rows separately for each reference angle, never mixing tunes.

    Within an angle, only rows at the same phase-DAC setting as the last selected row of that angle are
    averaged (rows from before a retune are left out and listed in ``dropped_stamps``).

    Args:
        events: BaseTab.events, {stamp: row dict} (rows may carry quad_ref_deg and phase_vout)
        stamps: selected stamps, in table order

    Returns:
        {angle: base_dict} built the way BaseTab.select_event builds its one dict (sweep-weighted average,
        most entries from the last row), or None if no selected row is a quadrature record
    """
    rows = [(s, events[s]) for s in stamps]
    if not any('quad_ref_deg' in row for _, row in rows):
        return None
    by_angle = {}
    for stamp, row in rows:
        by_angle.setdefault(angle_of(row), []).append((stamp, row))
    result = {}
    for angle, group in by_angle.items():
        vout = group[-1][1].get('phase_vout')
        keep = [(s, r) for s, r in group if same_vout(r.get('phase_vout'), vout)]
        phase, sweeps = None, 0
        for stamp, row in keep:
            p = np.array(row['phase'], dtype=float)
            n = row['sweeps']
            phase = p if phase is None else (phase * sweeps + p * n) / (sweeps + n)
            sweeps += n
        d = dict(keep[-1][1])
        d['sweeps'] = sweeps
        d['phase'] = phase
        d['base_stamps'] = [s for s, _ in keep]
        d['dropped_stamps'] = [s for s, r in group if not same_vout(r.get('phase_vout'), vout)]
        d['quad_ref_deg'] = angle
        d['phase_vout'] = vout
        result[angle] = d
    return result


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_calibration(record, directory):
    """Write a calibration record to <directory>/<cal_id>.json and return the path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{record['cal_id']}.json")
    with open(path, 'w') as f:
        json.dump(_jsonable(record), f)
        f.write('\n')
    return path


def latest_calibration(directory, channel=None):
    """Most recent calibration record in ``directory`` (optionally for one channel), or None."""
    for path in sorted(glob.glob(os.path.join(directory, '*.json')), reverse=True):
        try:
            with open(path) as f:
                record = json.load(f)
        except Exception as e:
            log.warning(f"Skipping unreadable calibration file {path}: {e}")
            continue
        if record.get('record_type') != 'quad_calibration':
            continue
        if channel is not None and record.get('channel') != channel:
            continue
        return record
    return None
