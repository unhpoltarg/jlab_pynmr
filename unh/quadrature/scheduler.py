"""Which Phase Tune each event uses, and the quadrature fields recorded with it. No Qt, no hardware.

The operator's tunes are kept by nominal angle: 0 (Real) and 90 (Imag), plus 180/270 for cycle4. While
quadrature is on, events step through the configured sequence of angles. One pass through the sequence
is a group (``quad_group``); ``quad_index`` is the position within it.
"""
import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

from .calfit import angle_at, gain_at
from .settings import sequence_name

log = logging.getLogger('PyNMR.unh.quadrature')

TUNE_TOL = 1e-6   # tunes closer than this (DAC fraction) count as the same setting
FREQ_TOL_MHZ = 0.05   # a calibration is for one centre frequency: the shifter's phase curve depends strongly on it


@dataclass
class Assignment:
    """One event's place in the quadrature sequence and the DAC setting it needs."""
    angle: int                 # nominal reference angle, deg
    vout: float                # Phase Tune for this event (DAC fraction 0..1)
    write_dac: bool            # the box must hold this tune before the event's sweeps start
    tags: dict = field(default_factory=dict)   # quad_* fields for the event record; {} when quadrature is off
    dac_ok: Optional[bool] = None              # result of the write that put this tune on the box
    event: object = None                       # the EventData taken with this assignment


class Scheduler:
    """Steps events through the sequence.

    Args:
        sequence: list of nominal angles, starting at 0 by convention (see settings.sequence_of)
        settle_ms: wait after each DAC write, ms
    """

    def __init__(self, sequence, settle_ms):
        self.sequence = list(sequence)
        self.settle_ms = float(settle_ms)
        self.tunes = {0: None, 90: None, 180: None, 270: None}
        self.active = False         # the operator's Quadrature checkbox
        self.suspended = None       # reason string once quadrature is suspended during a run, else None
        self.calibration = None     # latest calibration record (dict), or None
        self._pos = 0
        self._group_n = 0
        self._run_stamp = None
        self._dac_vout = None       # what the box was last told by the run loop, None = unknown
        self.context = {}           # {'channel': name, 'cent_freq': MHz} of the Config in use, set by the controller

    # -- tunes -------------------------------------------------------------
    def missing_tunes(self):
        """Angles the sequence needs that have no tune set."""
        return sorted({a for a in self.sequence if self.tunes.get(a) is None})

    def same(self, a, b):
        return a is not None and b is not None and abs(float(a) - float(b)) < TUNE_TOL

    # -- run lifecycle -----------------------------------------------------
    def start_run(self, now=None):
        """Called before the first event of a run."""
        now = now or datetime.datetime.now(tz=datetime.timezone.utc)
        self._run_stamp = now.strftime('%Y-%m-%d_%H-%M-%S')
        self._pos = 0
        self._group_n = 0
        self.suspended = None
        self._dac_vout = None       # the box may have been retuned from the Tune tab since the last run
        self._last_ok = None

    def suspend(self, reason):
        """Stop alternating for the rest of the run; events use the Real tune."""
        if self.suspended is None:
            self.suspended = reason
            log.error(f"Quadrature suspended: {reason}. The rest of the run uses the Real tune.")

    def next_assignment(self, current_vout):
        """The next event's angle, tune and tags.

        Args:
            current_vout: phase_vout of the Config in use (what the box holds if nothing else wrote it)

        Returns:
            Assignment. With quadrature off: angle 0 and the Real tune, tags {}; the DAC is written only if
            the Config isn't already on the Real tune (the Tune tab was left on Imag).
        """
        real = self.tunes[0] if self.tunes[0] is not None else current_vout
        if not self.active:
            return Assignment(0, real, write_dac=not self.same(real, current_vout))
        if self.suspended is not None:
            a = Assignment(0, real, write_dac=not self.same(real, self._dac_vout))
            a.tags = self._tags(0, real, group=None, index=None, state='suspended')
            return a
        if self._pos == 0:
            self._group_n += 1
        angle = self.sequence[self._pos]
        index = self._pos
        self._pos = (self._pos + 1) % len(self.sequence)
        vout = self.tunes[angle]
        a = Assignment(angle, vout, write_dac=True)
        a.tags = self._tags(angle, vout, group=f'{self._run_stamp}_{self._group_n:04d}', index=index, state='ok')
        return a

    def peek_next(self):
        """The tune the next event will use, without advancing the sequence; None if not alternating."""
        if not self.active or self.suspended is not None:
            return None
        return self.tunes[self.sequence[self._pos]]

    def box_written(self, vout, ok):
        """Record a phase-DAC write (GUI thread at run start, run thread at the end of an event)."""
        self._last_ok = bool(ok)
        if ok:
            self._dac_vout = vout
        else:
            self._dac_vout = None
            if self.active:
                self.suspend(f'the box did not accept phase DAC {vout:.4f}')

    def dac_written(self, assignment, ok):
        """Record the write that put this assignment's tune on the box."""
        assignment.dac_ok = bool(ok)
        self.box_written(assignment.vout, ok)

    # -- record fields -----------------------------------------------------
    def _tags(self, angle, vout, group, index, state):
        tunes = {str(a): float(v) for a, v in self.tunes.items() if v is not None}
        tags = {
            'quad_mode': sequence_name(self.sequence),
            'quad_sequence': list(self.sequence),
            'quad_state': state,
            'quad_ref_deg': int(angle),
            'quad_vout': float(vout),
            'quad_tunes': tunes,
            'quad_group': group,
            'quad_index': index,
            'quad_settle_ms': self.settle_ms,
            'quad_dac_ok': None,
            'quad_dac_set': None,
            'quad_cal_id': None,
            'quad_cal_angle_deg': None,
            'quad_cal_gain': None,
            'quad_cal_valid': None,
            'quad_base_ref_deg': None,
        }
        cal = self.calibration
        if cal:
            fit = cal.get('fit')
            tags['quad_cal_id'] = cal.get('cal_id')
            if fit and fit.get('success'):
                real = self.tunes[0]
                # angle of this tune relative to the current Real tune, from the fitted map
                a_this, a_real = angle_at(fit, vout), angle_at(fit, real)
                g_this, g_real = gain_at(fit, vout), gain_at(fit, real)
                tags['quad_cal_angle_deg'] = a_this - a_real
                tags['quad_cal_gain'] = g_this / g_real
                lo, hi = fit['phi_table']['vout'][0], fit['phi_table']['vout'][-1]
                tags['quad_cal_valid'] = bool(self.calibration_valid() and lo - TUNE_TOL <= vout <= hi + TUNE_TOL)
            else:
                tags['quad_cal_valid'] = False
        return tags

    def calibration_valid(self, channel=None, cent_freq=None):
        """True if the latest calibration was taken with the current tunes, on the same channel and at the same
        centre frequency (within FREQ_TOL_MHZ). channel and cent_freq default to self.context."""
        cal = self.calibration
        if not cal or not (cal.get('fit') or {}).get('success'):
            return False
        for angle, v in cal.get('tunes', {}).items():
            if not self.same(v, self.tunes.get(int(angle))):
                return False
        channel = channel if channel is not None else self.context.get('channel')
        cent_freq = cent_freq if cent_freq is not None else self.context.get('cent_freq')
        if channel is not None and cal.get('channel') != channel:
            return False
        if cent_freq is not None and cal.get('cent_freq') is not None                 and abs(float(cal['cent_freq']) - float(cent_freq)) > FREQ_TOL_MHZ:
            return False
        return True
