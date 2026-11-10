"""Auto Tune: find the true 0/90/180/270 deg Phase Tunes from the background Q-curve. Pure numpy/scipy.

The operator sets each tune by hand to within a few tens of degrees. Auto Tune then:
1. steps the phase DAC through a few values around each tune (a local calibration, calfit.fit_calibration),
   which gives W(f), the complex response in the Real tune's frame, and the phase phi(v) of each DAC value;
2. fits the trace W(f) and finds theta_ref, its normal at the reference frequency (the window centre);
3. moves each tune to the DAC value whose phase is theta_ref (0 deg), theta_ref + 90 (90 deg), and so on.

Why the normal. Absorption by the sample adds resistance to the coil; sweeping the frequency changes the
tank's reactance. Both reach the detector through the same circuit, so at every frequency the NMR
absorption at that frequency points along the normal to the Q-curve trace there. The absorptive phase
therefore turns across the sweep exactly as the angle about the trace's circle does,
theta(f) = theta0 + 2 atan((f - f0)/gamma). Auto Tune uses the normal at the centre frequency, where the
line sits. It doesn't need the resonance point f0, which a +-200 kHz window pins down poorly. (Checked
against the simulator's Q-meter: within 0.5 deg for a straight trace, a Q ~ 26 circle and a circle with a
lambda/2 cable, with the tank detuned by up to 200 kHz.)

Trace fit (geometric, 2026-11-04). The points W(f) are fitted with a circle written as a conic,
A (x^2 + y^2) + B x + C y + D = 0 with Pratt's constraint B^2 + C^2 - 4 A D = 1, so it stays finite as the
circle straightens into a line (A -> 0; the constant-current Liverpool Q-meter with a large R_cc gives an
almost straight trace). The normal at the point nearest the centre frequency is the gradient there,
atan2(2 A y + C, 2 A x + B). Its error comes from a jackknife over the bins, folded mod 180 deg. This replaced
a parametric fit in f, which was pulled by uneven frequency spacing along the trace and fitted poorly.

A symmetric deuteron line centred on the window adds an even function along the normal and an odd one
along the tangent, so it doesn't tilt the normal at the centre to first order. Bins can also be masked out.

Choices that the data can't make, left to the operator's hand tunes:
- 0 or 180 deg: theta_ref and theta_ref + 180 are both absorptive; 0 deg is the one nearer the hand Real tune.
- +90 or -90 deg: the sign of the rotation isn't observable (see calfit); 90 deg is the dispersive direction
  nearer the hand Imag tune. 180 and 270 deg are then opposite 0 and 90.
"""
import numpy as np

from . import calfit


def _conic_fit(x, y):
    """Pratt fit of A(x^2 + y^2) + B x + C y + D = 0 (a circle, or a line when A -> 0) to points.

    Returns (A, B, C, D) normalised so B^2 + C^2 - 4AD = 1. Geometric: no frequency model, so it
    fits the trace's shape whatever the point spacing along it.
    """
    z = x * x + y * y
    Z = np.column_stack([z, x, y, np.ones_like(x)])
    M = Z.T @ Z
    Bc = np.array([[0, 0, 0, -2.0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [-2.0, 0, 0, 0]])
    w, v = np.linalg.eig(np.linalg.solve(Bc, M))
    w = np.real(w)
    v = np.real(v)
    best = None
    for k in range(4):
        a = v[:, k]
        n = a[1] ** 2 + a[2] ** 2 - 4 * a[0] * a[3]
        if n <= 0:
            continue
        a = a / np.sqrt(n)
        cost = a @ M @ a
        if best is None or cost < best[0]:
            best = (cost, a)
    if best is None:
        raise ValueError('trace fit failed')
    return tuple(best[1])


def _normal_at(a, px, py):
    """Angle (rad) of the conic's normal (its gradient) at the point (px, py)."""
    A, B, C, _D = a
    return float(np.arctan2(2 * A * py + C, 2 * A * px + B))


def _ref_point(f, W, ref):
    """The trace at ``ref`` (complex), by linear interpolation between the bins either side."""
    return complex(np.interp(ref, f, W.real), np.interp(ref, f, W.imag))


def _trace_normal(f, W, ref, z0, sc):
    """(normal angle rad, conic, scaled reference point) for bins ``W`` (scaled by z0, sc)."""
    u = (W - z0) / sc
    a = _conic_fit(u.real, u.imag)
    pr = (_ref_point(f, W, ref) - z0) / sc
    return _normal_at(a, pr.real, pr.imag), a, pr


def fit_trace(freqs_MHz, W, mask=None, ref_MHz=None):
    """Fit the geometry of the complex response W(f) and find its normal at ``ref_MHz``.

    The bins are fitted with a circle that may straighten into a line (Pratt conic fit), with no model of
    how fast the trace moves with frequency: in the real circuit the bow (set mainly by the constant-current
    resistor) and the spacing along the trace (set by the tank reactance's frequency dependence) are
    independent, and fitting both with one model trades the few-mV bow for the tens-of-mV spacing. The
    absorptive direction at ref is the normal to the fitted curve at the trace's point there (interpolated
    between the two neighbouring bins). Its error is a jackknife over the bins.

    Args:
        freqs_MHz: bin centre frequencies, MHz
        W: complex response in each bin (V), in the Real tune's frame
        mask: boolean array, True for bins to use (default all)
        ref_MHz: frequency where the absorptive direction is wanted (default: the window centre)

    Returns:
        dict (JSON-ready): theta_ref_deg (the absorptive direction at ref) and its error, the circle (centre_V,
        radius_V; None for a straight trace), arc_deg spanned by the bins, ref_point_V, curve_V (the fitted
        curve over the bins, for plotting), residual_rms_V (distance of the bins from the curve) and
        residual_rel (over the trace's span), success
    """
    f = np.asarray(freqs_MHz, dtype=float)
    W = np.asarray(W, dtype=complex)
    if mask is not None:
        f, W = f[np.asarray(mask, dtype=bool)], W[np.asarray(mask, dtype=bool)]
    if len(f) < 6:
        return {'success': False, 'message': f'only {len(f)} frequency bins'}
    order = np.argsort(f)
    f, W = f[order], W[order]
    ref = 0.5 * (f.min() + f.max()) if ref_MHz is None else float(ref_MHz)
    z0 = W.mean()
    sc = max(float(np.max(np.abs(W - z0))), 1e-12)
    try:
        theta, a, pr = _trace_normal(f, W, ref, z0, sc)
    except Exception as e:
        return {'success': False, 'message': f'trace fit failed: {e}'}
    # jackknife over the bins for the error of the normal
    jk = []
    for k in range(len(f)):
        keep = np.arange(len(f)) != k
        try:
            jk.append(_trace_normal(f[keep], W[keep], ref, z0, sc)[0])
        except Exception:
            pass
    # a normal and its reverse are the same direction: fold each refit onto theta (mod 180 deg) first
    dev = np.array([(np.angle(np.exp(2j * (t - theta)))) / 2.0 for t in jk])
    err = float(np.sqrt((len(dev) - 1) / len(dev) * np.sum((dev - dev.mean()) ** 2))) if len(dev) > 2 else float('nan')
    A, B, C, D = a
    u = (W - z0) / sc
    grad = np.hypot(2 * A * u.real + B, 2 * A * u.imag + C)
    resid = (A * np.abs(u) ** 2 + B * u.real + C * u.imag + D) / np.where(grad > 0, grad, 1.0) * sc
    curved = abs(A) > 1e-9
    centre = radius = None
    arc = 0.0
    if curved:
        cu = complex(-B / (2 * A), -C / (2 * A))
        r2 = abs(cu) ** 2 - D / A
        if r2 > 0:
            centre = z0 + cu * sc
            radius = float(np.sqrt(r2) * sc)
            ang = np.unwrap(np.angle(W - centre))
            arc = float(np.degrees(np.ptp(ang)))
            t = np.linspace(ang.min(), ang.max(), 200)
            curve = centre + radius * np.exp(1j * t)
        else:
            curved = False
    if not curved or centre is None:
        n = np.exp(1j * np.arctan2(C, B))                     # line: normal n, points p with Re(p conj n) = const
        tdir = 1j * n
        proj = np.real((W - z0) * np.conj(tdir))
        off = -D / np.hypot(B, C) * sc
        curve = z0 + off * n + tdir * np.linspace(proj.min(), proj.max(), 200)
    p_ref = z0 + pr * sc
    span = float(np.max(np.abs(W - W.mean()))) or 1e-12
    rms = float(np.sqrt(np.mean(resid ** 2)))
    return {
        'model': 'geometric circle-or-line (Pratt conic) through the bins; normal at the trace point at ref_MHz',
        'ref_MHz': ref,
        'theta_ref_deg': float(np.degrees(np.angle(np.exp(1j * theta)))),
        'theta_ref_err_deg': float(np.degrees(err)),
        'arc_deg': arc,
        'centre_V': None if centre is None else [float(centre.real), float(centre.imag)],
        'radius_V': radius,
        'ref_point_V': [float(p_ref.real), float(p_ref.imag)],
        'curve_V': [[float(c.real), float(c.imag)] for c in curve],
        'residual_rms_V': rms,
        'residual_rel': rms / span,
        'n_bins': int(len(f)),
        'success': True,
        'message': 'ok',
    }


def _wrap180(x):
    return (np.asarray(x, dtype=float) + 180.0) % 360.0 - 180.0


def wing_curvature(freqs, y, outer=0.5, with_error=False):
    """Quadratic coefficient (in units of y) of y over the outer part of the window (|x| > outer, x = +-1 at the
    edges), clear of the deuteron line: > 0 a smile, < 0 a frown. With ``with_error``, (value, standard error)."""
    f = np.asarray(freqs, dtype=float)
    x = (f - 0.5 * (f.min() + f.max())) / max(0.5 * np.ptp(f), 1e-12)
    m = np.abs(x) > outer
    if m.sum() < 5:
        return (float('nan'), float('nan')) if with_error else float('nan')
    p, cov = np.polyfit(x[m], np.asarray(y, dtype=float)[m], 2, cov=True)
    return (float(p[0]), float(np.sqrt(max(cov[0, 0], 0.0)))) if with_error else float(p[0])


def frown_zero(freqs, W, theta_deg, diode_curv):
    """Which absorptive direction is 0 deg: the one whose phase output curves opposite to the diode (JLab: a
    diode smile goes with a frown at the in-tune Real phase). ``diode_curv`` is (value, error). Returns
    (zero_deg or None, note); None when either curvature is within 3 standard errors of zero, so the hand tune
    decides."""
    c, ce = wing_curvature(freqs, np.real(np.asarray(W) * np.exp(-1j * np.radians(theta_deg))), with_error=True)
    diode_curv, de = diode_curv
    if not (np.isfinite(c) and np.isfinite(diode_curv)) or abs(c) < 3 * ce or abs(diode_curv) < 3 * de:
        return None, 'curvature too small to tell; nearest the hand Real tune'
    zero = theta_deg if np.sign(c) != np.sign(diode_curv) else theta_deg + 180.0
    shape = 'smile' if diode_curv > 0 else 'frown'
    return zero, f"phase {'frown' if shape == 'smile' else 'smile'} opposite the diode {shape}"


def target_angles(theta0_deg, hand_deg, zero_deg=None):
    """Target phase (deg, in the Real tune's frame) for each tune.

    Args:
        theta0_deg: absorptive direction (fit_trace's theta_ref_deg)
        hand_deg: {angle: measured phase of the operator's tune}; must contain 0 and 90 if 180/270 are present
        zero_deg: the absorptive direction to call 0 deg (from frown_zero); default: the one nearer the hand tune

    Returns:
        {angle: target phase}, each unwrapped to lie within 180 deg of the hand tune's phase
    """
    out = {}
    hand = {int(a): float(v) for a, v in hand_deg.items()}
    zero = None
    if 0 in hand:
        c = [theta0_deg, theta0_deg + 180.0]
        zero = zero_deg if zero_deg is not None else min(c, key=lambda t: abs(_wrap180(t - hand[0])))
        out[0] = hand[0] + float(_wrap180(zero - hand[0]))
    quad = None
    if 90 in hand:
        c = [theta0_deg + 90.0, theta0_deg - 90.0]
        quad = min(c, key=lambda t: abs(_wrap180(t - hand[90])))
        out[90] = hand[90] + float(_wrap180(quad - hand[90]))
    for angle, partner_target in ((180, zero), (270, quad)):
        if angle in hand and partner_target is not None:
            t = partner_target + 180.0
            out[angle] = hand[angle] + float(_wrap180(t - hand[angle]))
    return out


def solve_dac(levels, phi_deg, target_deg, centre):
    """DAC value whose phase is ``target_deg``, from the levels measured around one tune.

    A low-order polynomial phi(v) is fitted to the cluster (quadratic with 4 or more levels) and solved for
    the root nearest ``centre``.

    Returns:
        (vout, inside): inside is False when the answer lies outside the measured levels (extrapolated)
    """
    v = np.asarray(levels, dtype=float)
    p = np.asarray(phi_deg, dtype=float)
    deg = 2 if len(v) >= 4 else 1
    c = np.polyfit(v - centre, p, deg)
    c[-1] -= target_deg
    roots = np.roots(c)
    roots = roots[np.abs(roots.imag) < 1e-9].real + centre
    if roots.size == 0:
        c1 = np.polyfit(v - centre, p, 1)
        roots = np.array([centre + (target_deg - c1[1]) / c1[0]])
    vout = float(roots[np.argmin(np.abs(roots - centre))])
    inside = bool(v.min() - 1e-9 <= vout <= v.max() + 1e-9)
    return vout, inside


def step_plan(centres, offsets, v_lo, v_hi):
    """Steps for one Auto Tune pass: the Real tune first and last, and a cluster around each tune.

    Args:
        centres: {angle: vout} present tunes (must include 0)
        offsets: DAC offsets of the cluster points around each tune, e.g. [-0.03, -0.015, 0, 0.015, 0.03]
        v_lo, v_hi: usable DAC range

    Returns:
        list of dicts {vout, pass, kind, angle} in the order taken; kind 'ref' is the Real tune itself
    """
    v_real = float(centres[0])
    plan = [{'vout': v_real, 'pass': 1, 'kind': 'ref', 'angle': 0}]
    for angle in sorted(centres):
        c = float(centres[angle])
        for d in offsets:
            v = float(np.clip(round(c + d, 6), v_lo, v_hi))
            kind = 'ref' if abs(v - v_real) < 1e-9 else 'cluster'
            plan.append({'vout': v, 'pass': 1, 'kind': kind, 'angle': angle})
        plan.append({'vout': v_real, 'pass': 1, 'kind': 'ref', 'angle': 0})
    return plan


def _trace_of(fit, freqs_MHz, cfg):
    """fit_trace on a calibration fit's W, with the mask_khz bins left out. Returns (trace, bin freqs, W)."""
    bins = int(fit['bins'])
    W = np.asarray(fit['W_abs_V']) * np.exp(1j * np.radians(fit['W_angle_deg']))
    fb = calfit.bin_sweep(freqs_MHz, bins)
    mask = None
    if cfg.get('mask_khz'):
        fc = 0.5 * (fb.min() + fb.max())
        off = (fb - fc) * 1000.0
        mask = np.ones(len(fb), dtype=bool)
        for lo, hi in cfg['mask_khz']:
            mask &= ~((off >= lo) & (off <= hi))
    trace = fit_trace(fb, W, mask, ref_MHz=cfg.get('ref_MHz'))
    trace['bin_freqs_MHz'] = fb.tolist()
    trace['W_re_V'] = W.real.tolist()
    trace['W_im_V'] = W.imag.tolist()
    return trace, fb, W


def analyse_pass(steps, freqs_MHz, centres, cfg, v_range):
    """Fit one pass and work out the new tunes.

    Args:
        steps: list of dicts with vout, t_s, phase (one sweep per step), angle (cluster it belongs to)
        freqs_MHz: the sweep's frequency list, MHz
        centres: {angle: vout} the tunes this pass was centred on (0 = the Real tune, the phase reference)
        cfg: the 'autotune' settings dict
        v_range: (v_lo, v_hi) usable DAC range

    Returns:
        dict (JSON-ready): fit (calfit), trace (fit_trace), tunes {angle: {...}}, converged, success, message
    """
    bins = int(cfg['bins'])
    v_real = float(centres[0])
    fit = calfit.fit_calibration([s['vout'] for s in steps], [s['t_s'] for s in steps],
                                 [s['phase'] for s in steps], v_real, tunes=centres,
                                 gain_order=int(cfg['gain_order']), offset_order=int(cfg['offset_order']),
                                 fit_drift=bool(cfg['fit_drift']), bins=bins, v_range=v_range)
    out = {'fit': fit, 'trace': None, 'tunes': {}, 'converged': False, 'success': False, 'message': ''}
    if not fit.get('success'):
        out['message'] = f"local calibration fit failed: {fit.get('message')}"
        return out
    trace, fb, W = _trace_of(fit, freqs_MHz, cfg)
    out['trace'] = trace
    if not trace.get('success'):
        out['message'] = f"trace fit failed: {trace.get('message')}"
        return out
    table = fit['phi_table']
    lev = np.asarray(table['vout'])
    phi = np.asarray(table['phi_deg'])
    hand = {a: float(np.interp(v, lev, phi)) for a, v in centres.items()}
    zero, note = None, 'nearest the hand Real tune'
    if cfg.get('zero_by_curvature', True):
        diodes = [np.asarray(s['diode'], dtype=float) for s in steps if s.get('diode') is not None]
        if diodes and len(diodes[0]) == len(freqs_MHz):
            dcurv = wing_curvature(freqs_MHz, np.mean(diodes, axis=0), with_error=True)
            zero, note = frown_zero(fb, W, trace['theta_ref_deg'], dcurv)
    if zero is not None and min(abs(float(_wrap180(zero - h))) for h in hand.values()) > 60.0:
        # a local scan can't reach half a turn away: keep the nearer absorptive setting and say so
        zero = None
        note = ('Real is on the smile side (same curvature as the diode); the JLab frown is half a turn away. '
                'Kept the nearer absorptive setting: set Real about half a turn away by hand, or use cycle4')
        out['zero_warning'] = note
    trace['zero_rule'] = note
    targets = target_angles(trace['theta_ref_deg'], hand, zero_deg=zero)
    half = max(abs(d) for d in cfg['offsets']) + 1e-6
    converged = True
    for angle, target in targets.items():
        # solve within the steps of the measured tune nearest the target: in cycle4 the frown 0 deg may sit
        # by the hand 180 deg tune (and 180 deg by the hand Real tune)
        near_angle = min(hand, key=lambda a: abs(float(_wrap180(target - hand[a]))))
        c = float(centres[near_angle])
        near = np.abs(lev - c) <= half
        local = hand[near_angle] + float(_wrap180(target - hand[near_angle]))   # same turn as those steps
        vout, inside = solve_dac(lev[near], phi[near], local, c)
        vout = float(np.clip(vout, v_range[0], v_range[1]))
        converged &= inside
        out['tunes'][str(angle)] = {
            'from_vout': float(centres[angle]), 'to_vout': round(vout, 5), 'inside': inside,
            'hand_phase_deg': hand[angle], 'target_phase_deg': float(target),
            'moved_deg': float(target - hand[angle]),
            'gain_ratio': calfit.gain_at(fit, vout),
        }
    out['converged'] = bool(converged)
    out['success'] = True
    return out


# --- Auto Tune with a coarse map first (autotune: map: True) -----------------------------------------------
#
# 1. A coarse scan over the whole phase-DAC range (map_plan), fitted like a calibration (analyse_map): the phase and
#    gain at every setting, where the shifter goes flat, and the absorptive direction from the Q-curve. The shifter
#    covers more than a turn, so some angles can be reached at two settings a turn apart: every such setting is a
#    candidate (candidates_for).
# 2. Local passes around every candidate (cluster_plan, analyse_snap): each is moved to the nearest quadrature
#    direction and its gain measured.
# 3. The combination of settings with the most equal gains is kept, ties going to the larger signal
#    (choose_combination); a polish pass around it gives the final tunes.
# Which dispersive side is 90 deg can't be measured (phi -> -phi, W -> conj W gives the same data). In the map's frame
# (phase increasing with DAC, as calfit reports it) 90 deg is zero + 90 * side90, with side90 = +1 or -1 kept from the
# last Auto Tune; the first time it comes from the hand Imag tune.


def map_plan(v_ref, v_lo, v_hi, steps, ref_every):
    """Coarse-map steps: an evenly spaced grid over [v_lo, v_hi], one way, with returns to v_ref (first and last too).

    Returns:
        list of dicts {vout, pass, kind, angle}: kind 'grid' or 'ref'; angle is 'map'
    """
    plan = calfit.step_plan({'v_min': v_lo, 'v_max': v_hi, 'steps': int(steps), 'passes': 1,
                             'ref_every': int(ref_every)}, float(v_ref))
    for p in plan:
        p['angle'] = 'map'
    return plan


def side_from_hand(phi_hand90, zero_deg):
    """+1 if the hand Imag tune's phase is nearer zero + 90 deg, -1 if nearer zero - 90 deg."""
    plus = abs(float(_wrap180(phi_hand90 - (zero_deg + 90.0))))
    minus = abs(float(_wrap180(phi_hand90 - (zero_deg - 90.0))))
    return 1 if plus <= minus else -1


def quad_targets(zero_deg, side90, angles):
    """Target phase (deg, map frame) of each angle: 0 -> zero, 90 -> zero + 90 side90, 180 and 270 opposite."""
    t = {0: zero_deg, 90: zero_deg + 90.0 * side90, 180: zero_deg + 180.0, 270: zero_deg - 90.0 * side90}
    return {int(a): float(t[int(a)]) for a in angles}


def candidates_for(levels, phi_deg, target_deg, v_lo, v_hi):
    """Every DAC value in [v_lo, v_hi] whose phase is target_deg modulo 360 (linear between the map's levels)."""
    lev = np.asarray(levels, dtype=float)
    phi = np.degrees(np.unwrap(np.radians(np.asarray(phi_deg, dtype=float))))
    keep = (lev >= v_lo - 1e-9) & (lev <= v_hi + 1e-9)
    lev, phi = lev[keep], phi[keep]
    if len(lev) < 2:
        return []
    dense = np.linspace(lev.min(), lev.max(), 20001)
    p = np.interp(dense, lev, phi)
    out = []
    k_lo = int(np.floor((p.min() - target_deg) / 360.0)) - 1
    k_hi = int(np.ceil((p.max() - target_deg) / 360.0)) + 1
    for k in range(k_lo, k_hi + 1):
        t = target_deg + 360.0 * k
        for i in np.nonzero(np.diff(np.sign(p - t)))[0]:
            v = dense[i] + (t - p[i]) * (dense[i + 1] - dense[i]) / (p[i + 1] - p[i])
            out.append(round(float(v), 5))
    return sorted(set(out))


def choose_combination(gains, tie=0.003):
    """The candidate settings with the most equal gains.

    Args:
        gains: {angle: {vout: gain}} candidates for every angle (gains on one common scale)
        tie: combinations whose spread is within this of the best count as tied; the larger mean gain wins

    Returns:
        ({angle: vout}, spread): spread = max gain / min gain - 1 of the chosen settings
    """
    import itertools
    angles = sorted(gains)
    combos = []
    for pick in itertools.product(*[sorted(gains[a].items()) for a in angles]):
        g = np.array([x[1] for x in pick])
        combos.append((float(g.max() / g.min() - 1.0), float(g.mean()), {a: x[0] for a, x in zip(angles, pick)}))
    best = min(c[0] for c in combos)
    tied = [c for c in combos if c[0] <= best + tie]
    spread, _, choice = max(tied, key=lambda c: c[1])
    return choice, spread


def analyse_map(steps, freqs_MHz, v_ref, cfg, v_range, angles, side90=None, hand=None):
    """Fit the coarse map and list the candidate settings for each angle.

    Args:
        steps: map steps (vout, t_s, phase, diode)
        v_ref: the reference DAC value (the hand Real tune; phase 0 of the map's frame)
        cfg: the 'autotune' settings dict
        v_range: (v_lo, v_hi) usable DAC range
        angles: the angles wanted (0 and 90, plus 180/270 for cycle4)
        side90: +1/-1 kept from the last Auto Tune, or None to take it from hand[90]
        hand: {angle: vout} the operator's tunes (for side90 the first time, and to report how far off they were)

    Returns:
        dict (JSON-ready): fit, trace, zero_deg, zero_rule, side90, side90_source, targets, usable range,
        candidates {angle: [vout, ...]}, map_gain {angle: {vout: gain}}, hand_error_deg, success, message
    """
    fit = calfit.fit_calibration([s['vout'] for s in steps], [s['t_s'] for s in steps],
                                 [s['phase'] for s in steps], float(v_ref),
                                 gain_order=int(cfg['map_gain_order']), offset_order=int(cfg['offset_order']),
                                 fit_drift=bool(cfg['fit_drift']), bins=int(cfg['bins']), v_range=v_range)
    out = {'fit': fit, 'trace': None, 'success': False, 'message': ''}
    if not fit.get('success'):
        out['message'] = f"map fit failed: {fit.get('message')}"
        return out
    trace, fb, W = _trace_of(fit, freqs_MHz, cfg)
    out['trace'] = trace
    if not trace.get('success'):
        out['message'] = f"trace fit failed: {trace.get('message')}"
        return out
    theta = float(trace['theta_ref_deg'])
    lev = np.asarray(fit['phi_table']['vout'])
    phi = np.asarray(fit['phi_table']['phi_deg'])
    zero, note = None, None
    if cfg.get('zero_by_curvature', True):
        diodes = [np.asarray(s['diode'], dtype=float) for s in steps if s.get('diode') is not None]
        if diodes and len(diodes[0]) == len(freqs_MHz):
            dcurv = wing_curvature(freqs_MHz, np.mean(diodes, axis=0), with_error=True)
            zero, note = frown_zero(fb, W, theta, dcurv)
    if zero is None:                       # the absorptive direction nearer the hand Real tune (phase 0 here)
        zero = min((theta, theta + 180.0), key=lambda t: abs(float(_wrap180(t))))
        note = note or 'nearest the hand Real tune'
    hand = {int(a): float(v) for a, v in (hand or {}).items() if v is not None}
    if side90 in (1, -1):
        source = 'kept from the last Auto Tune'
    elif 90 in hand and 0 in hand and abs(hand[90] - hand[0]) >= 0.01:
        side90 = side_from_hand(float(np.interp(hand[90], lev, phi)), zero)
        source = 'from the hand Imag tune'
    else:
        side90 = 1
        source = 'default (no hand Imag tune)'
    targets = quad_targets(zero, side90, angles)
    lo, hi = float(v_range[0]), float(v_range[1])
    clip = fit.get('clip_vout')
    if clip is not None:
        hi = min(hi, float(clip) - float(cfg.get('clip_margin', 0.01)))
    cands, gains = {}, {}
    for a, t in targets.items():
        cands[a] = candidates_for(lev, phi, t, lo, hi)
        gains[a] = {v: calfit.gain_at(fit, v) for v in cands[a]}
    out.update({
        'zero_deg': float(zero), 'zero_rule': note, 'side90': int(side90), 'side90_source': source,
        'targets': {str(a): t for a, t in targets.items()}, 'usable': [lo, hi], 'clip_vout': clip,
        'candidates': {str(a): c for a, c in cands.items()},
        'map_gain': {str(a): {str(v): g for v, g in gains[a].items()} for a in gains},
        'hand_error_deg': {str(a): float(_wrap180(np.interp(v, lev, phi) - targets[a]))
                           for a, v in hand.items() if a in targets},
    })
    missing = [a for a, c in cands.items() if not c]
    if missing:
        out['message'] = ("no phase-DAC setting below the shifter's flat top reaches "
                          + ', '.join(f'{a} deg' for a in missing))
        return out
    out['success'] = True
    out['message'] = 'ok'
    return out


def cluster_plan(v_ref, centres, offsets, v_lo, v_hi):
    """Steps for a local pass: v_ref first and after each cluster, and a cluster around each centre.

    Args:
        centres: {key: vout}; the key labels the cluster (any hashable)

    Returns:
        list of dicts {vout, pass, kind, angle}; angle is the cluster's key ('ref' for the returns to v_ref)
    """
    ref = {'vout': float(v_ref), 'pass': 1, 'kind': 'ref', 'angle': 'ref'}
    plan = [dict(ref)]
    for key, c in sorted(centres.items(), key=lambda kv: kv[1]):
        for d in offsets:
            v = float(np.clip(round(float(c) + d, 6), v_lo, v_hi))
            plan.append({'vout': v, 'pass': 1, 'kind': 'ref' if abs(v - v_ref) < 1e-9 else 'cluster', 'angle': key})
        plan.append(dict(ref))
    return plan


def analyse_snap(steps, freqs_MHz, v_ref, centres, cfg, v_range, offsets):
    """Fit a local pass and move each cluster's centre to the nearest quadrature direction.

    Snapping to the nearest of theta, theta + 90, theta + 180, theta + 270 needs no labels and no sign convention (a
    flipped frame flips everything together), so the map decides which setting is which angle and this pass only
    refines. A snap of more than snap_max_deg means the map was off by a lot: reported, not trusted.

    Returns:
        dict (JSON-ready): fit, trace, tunes {key: {from_vout, to_vout, inside, snap_deg, gain}}, converged,
        success, message
    """
    fit = calfit.fit_calibration([s['vout'] for s in steps], [s['t_s'] for s in steps],
                                 [s['phase'] for s in steps], float(v_ref),
                                 gain_order=int(cfg['gain_order']), offset_order=int(cfg['offset_order']),
                                 fit_drift=bool(cfg['fit_drift']), bins=int(cfg['bins']), v_range=v_range)
    out = {'fit': fit, 'trace': None, 'tunes': {}, 'converged': False, 'success': False, 'message': ''}
    if not fit.get('success'):
        out['message'] = f"local fit failed: {fit.get('message')}"
        return out
    trace, fb, W = _trace_of(fit, freqs_MHz, cfg)
    out['trace'] = trace
    if not trace.get('success'):
        out['message'] = f"trace fit failed: {trace.get('message')}"
        return out
    theta = float(trace['theta_ref_deg'])
    lev = np.asarray(fit['phi_table']['vout'])
    phi = np.asarray(fit['phi_table']['phi_deg'])
    half = max(abs(d) for d in offsets) + 1e-6
    snap_max = float(cfg.get('snap_max_deg', 30.0))
    converged, far = True, []
    for key, c in centres.items():
        near = np.abs(lev - c) <= half
        h = float(np.interp(c, lev[near], phi[near]))
        snap = min((float(_wrap180(theta + 90.0 * k - h)) for k in range(4)), key=abs)
        vout, inside = solve_dac(lev[near], phi[near], h + snap, c)
        vout = float(np.clip(vout, v_range[0], v_range[1]))
        converged &= inside
        if abs(snap) > snap_max:
            far.append(str(key))
        out['tunes'][str(key)] = {'from_vout': float(c), 'to_vout': round(vout, 5), 'inside': inside,
                                  'snap_deg': snap, 'gain': calfit.gain_at(fit, vout)}
    out['converged'] = bool(converged)
    if far:
        out['message'] = (f"the map was more than {snap_max:.0f} deg off at {', '.join(far)}; "
                          'try again, or set the tunes by hand and turn the map off')
        return out
    out['success'] = True
    out['message'] = 'ok'
    return out
