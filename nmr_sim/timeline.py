"""Scripted run timeline: polarization P(t) and line position per segment.

A timeline is an ordered list of segments, each lasting ``duration_s`` of
simulated time (None = forever; only allowed last). Each segment starts from
the P at the end of the previous one (P0) and may shift the line by
``line_offset_MHz`` (used for the off-resonance baseline segment, which mimics
moving the magnet field so the line leaves the sweep window).

Segment kinds (all times in simulated seconds, P as fractions):
    hold    P constant: ``P`` (number or "te"), or P0 if omitted
    spinup  P = P0 + (P_inf - P0)(1 - exp(-t/tau_s))          (DNP build-up)
    relax   P = P_eq + (P0 - P_eq) exp(-t/T1_s), P_eq default "te"  (T1 decay)

Single spin temperature is assumed throughout (P and Q tied by r).
"""

import math
from dataclasses import dataclass
from typing import Optional

H_J_S = 6.62607015e-34       # Planck constant, J s
KB_J_PER_K = 1.380649e-23    # Boltzmann constant, J/K

_SEGMENT_KEYS = {
    "hold": {"name", "kind", "duration_s", "line_offset_MHz", "P"},
    "spinup": {"name", "kind", "duration_s", "line_offset_MHz", "P_inf", "tau_s"},
    "relax": {"name", "kind", "duration_s", "line_offset_MHz", "T1_s", "P_eq"},
}


def p_te(larmor_MHz, T_K):
    """Thermal-equilibrium vector polarization of spin 1 (fraction).

    P = 2 sinh(x) / (1 + 2 cosh(x)),  x = h f / (k_B T)   (Brillouin, J = 1).
    Equal to lineshape.ratio_P(exp(x)).

    Args:
        larmor_MHz: Larmor frequency, MHz
        T_K: lattice temperature, K
    """
    x = H_J_S * larmor_MHz * 1e6 / (KB_J_PER_K * T_K)
    return 2.0 * math.sinh(x) / (1.0 + 2.0 * math.cosh(x))


def spinup_P(t_s, P0, P_inf, tau_s):
    """Exponential build-up P0 -> P_inf with time constant tau_s (s)."""
    return P0 + (P_inf - P0) * (1.0 - math.exp(-t_s / tau_s))


def relax_P(t_s, P0, P_eq, T1_s):
    """Exponential relaxation P0 -> P_eq with time constant T1_s (s)."""
    return P_eq + (P0 - P_eq) * math.exp(-t_s / T1_s)


@dataclass(frozen=True)
class TimelineState:
    """Simulated state at one instant."""
    name: str                 # segment name
    index: int                # segment index
    P: float                  # vector polarization, fraction
    line_offset_MHz: float    # line shift from the nominal Larmor frequency, MHz
    t_in_seg_s: float         # simulated seconds since the segment started


@dataclass(frozen=True)
class _Seg:
    name: str
    kind: str
    start_s: float
    duration_s: Optional[float]
    line_offset_MHz: float
    P0: float
    target: float             # hold: P; spinup: P_inf; relax: P_eq
    tconst_s: float           # spinup: tau; relax: T1; hold: unused

    def P_at(self, t):
        if self.kind == "hold":
            return self.target
        if self.kind == "spinup":
            return spinup_P(t, self.P0, self.target, self.tconst_s)
        return relax_P(t, self.P0, self.target, self.tconst_s)


class Timeline:
    """Piecewise P(t) built from a list of segment dicts.

    Args:
        segments: list of dicts (see module docstring)
        P_te: thermal-equilibrium polarization used for "te" and the initial P0
    """

    def __init__(self, segments, P_te):
        if not segments:
            raise ValueError("timeline needs at least one segment")
        self.P_te = float(P_te)
        self._segs = []
        start, P0 = 0.0, self.P_te
        for i, s in enumerate(segments):
            kind = s.get("kind")
            if kind not in _SEGMENT_KEYS:
                raise ValueError(f"timeline[{i}]: unknown kind {kind!r}")
            extra = set(s) - _SEGMENT_KEYS[kind]
            if extra:
                raise ValueError(f"timeline[{i}] ({kind}): unknown keys {sorted(extra)}")
            dur = s.get("duration_s")
            if dur is None and i != len(segments) - 1:
                raise ValueError(f"timeline[{i}]: only the last segment may have duration_s: null")
            if kind == "hold":
                target, tconst = self._P_value(s.get("P", P0)), 0.0
            elif kind == "spinup":
                target, tconst = self._P_value(s["P_inf"]), float(s["tau_s"])
            else:
                target, tconst = self._P_value(s.get("P_eq", "te")), float(s["T1_s"])
            seg = _Seg(name=s.get("name", f"{kind}{i}"), kind=kind, start_s=start,
                       duration_s=None if dur is None else float(dur),
                       line_offset_MHz=float(s.get("line_offset_MHz", 0.0)),
                       P0=P0, target=target, tconst_s=tconst)
            self._segs.append(seg)
            if dur is not None:
                P0 = seg.P_at(float(dur))
                start += float(dur)
        self.total_s = start

    def _P_value(self, v):
        if isinstance(v, str):
            if v != "te":
                raise ValueError(f"P value must be a number or 'te', got {v!r}")
            return self.P_te
        P = float(v)
        if abs(P) >= 1.0:
            raise ValueError(f"|P| must be < 1, got {P}")
        return P

    def state(self, t_s):
        """TimelineState at simulated time t_s (s). After the last finite
        segment, the final state is held."""
        t_s = max(0.0, float(t_s))
        for i, seg in enumerate(self._segs):
            end = None if seg.duration_s is None else seg.start_s + seg.duration_s
            if end is None or t_s < end:
                t = t_s - seg.start_s
                return TimelineState(seg.name, i, seg.P_at(t), seg.line_offset_MHz, t)
        seg = self._segs[-1]
        return TimelineState(seg.name, len(self._segs) - 1, seg.P_at(seg.duration_s),
                             seg.line_offset_MHz, seg.duration_s)

    def table(self):
        """List of (name, kind, start_s, duration_s, line_offset_MHz, P_start, P_end)."""
        rows = []
        for seg in self._segs:
            P_end = seg.P_at(seg.duration_s) if seg.duration_s is not None else seg.target
            rows.append((seg.name, seg.kind, seg.start_s, seg.duration_s,
                         seg.line_offset_MHz, seg.P0, P_end))
        return rows
