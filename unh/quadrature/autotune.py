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

Trace model. A circle written so that it stays finite as it straightens into a line (the constant-current
Liverpool Q-meter with a large R_cc gives an almost straight trace):

    W(f) = P0 + i exp(i theta0) s u / (1 - i k u),     u = f - f0
    normal angle at f:  theta0 + 2 atan(k (f - f0))

s > 0 is the speed |dW/df| at f0, and k = 1/gamma (k = 0 is a straight line; the radius is s / (2 |k|)).

A symmetric deuteron line centred on the window adds an even function along the normal and an odd one
along the tangent, so it doesn't tilt the normal at the centre to first order. Bins can also be masked out.

Choices that the data can't make, left to the operator's hand tunes:
- 0 or 180 deg: theta_ref and theta_ref + 180 are both absorptive; 0 deg is the one nearer the hand Real tune.
- +90 or -90 deg: the sign of the rotation isn't observable (see calfit); 90 deg is the dispersive direction
  nearer the hand Imag tune. 180 and 270 deg are then opposite 0 and 90.
"""
import numpy as np
from scipy import optimize

from . import calfit


def _model(p, u):
    p0r, p0i, theta, s, k, f0 = p
    du = u - f0
    return (p0r + 1j * p0i) + 1j * np.exp(1j * theta) * s * du / (1.0 - 1j * k * du)


def fit_trace(freqs_MHz, W, mask=None, ref_MHz=None):
    """Fit the trace model to the complex response W(f) and find its normal at ``ref_MHz``.

    Args:
        freqs_MHz: bin centre frequencies, MHz
        W: complex response in each bin (V), in the Real tune's frame
        mask: boolean array, True for bins to use (default all)
        ref_MHz: frequency where the absorptive direction is wanted (default: the window centre)

    Returns:
        dict (JSON-ready): theta_ref_deg (the absorptive direction at ref_MHz) and its error, the fitted
        circle (theta0_deg, f0_MHz, gamma_MHz and radius_V; None for a straight trace), arc_deg across the
        window, residual_rms_V and residual_rel (residual over the trace's span), success
    """
    f = np.asarray(freqs_MHz, dtype=float)
    W = np.asarray(W, dtype=complex)
    if mask is not None:
        f, W = f[np.asarray(mask, dtype=bool)], W[np.asarray(mask, dtype=bool)]
    if len(f) < 6:
        return {'success': False, 'message': f'only {len(f)} frequency bins'}
    fc = 0.5 * (f.min() + f.max())
    h = max(0.5 * np.ptp(f), 1e-9)
    ref = fc if ref_MHz is None else float(ref_MHz)
    u_ref = (ref - fc) / h
    u = (f - fc) / h                                     # work in units of the window half-width
    b, a = np.polyfit(u, W, 1)                           # straight-line start: tangent b, resonance point a
    theta_start = np.angle(b) - np.pi / 2

    def resid(p):
        r = _model(p, u) - W
        return np.r_[r.real, r.imag]

    best = None
    for k0 in (0.0, 0.5, -0.5, 1.5, -1.5):
        p0 = [a.real, a.imag, theta_start, abs(b), k0, 0.0]
        lo = [-np.inf, -np.inf, -np.inf, 0.0, -50.0, -5.0]
        hi = [np.inf, np.inf, np.inf, np.inf, 50.0, 5.0]
        try:
            r = optimize.least_squares(resid, p0, bounds=(lo, hi), x_scale='jac', max_nfev=2000)
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    if best is None:
        return {'success': False, 'message': 'trace fit failed'}
    p = best.x
    r = resid(p)
    dof = max(1, r.size - len(p))
    s2 = float(np.sum(r ** 2) / dof)
    def normal(q):
        return q[2] + 2.0 * np.arctan(q[4] * (u_ref - q[5]))

    theta_ref = float(normal(p))
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * s2
        grad = np.array([(normal(p + dp) - normal(p - dp)) / (2e-6) for dp in np.eye(len(p)) * 1e-6])
        theta_err = float(np.sqrt(max(grad @ cov @ grad, 0.0)))
    except Exception:
        theta_err = float('nan')
    theta = float(np.angle(np.exp(1j * p[2])))
    s, k = float(p[3]) / h, float(p[4]) / h             # back to MHz
    span = float(np.max(np.abs(W - W.mean()))) or 1e-12
    rms = float(np.sqrt(np.mean(r ** 2)))
    curved = abs(p[4]) > 1e-3
    return {
        'model': 'W(f) = P0 + i exp(i theta0) s u / (1 - i k u), u = f - f0;'
                 ' about the circle centre theta(f) = theta0 + 2 atan(k (f - f0))',
        'ref_MHz': ref,
        'theta_ref_deg': float(np.degrees(np.angle(np.exp(1j * theta_ref)))),
        'theta_ref_err_deg': float(np.degrees(theta_err)),
        'arc_deg': float(np.degrees(abs(2 * np.arctan(p[4] * (u.max() - p[5])) - 2 * np.arctan(p[4] * (u.min() - p[5]))))),
        'theta0_deg': float(np.degrees(theta)),
        'f0_MHz': float(fc + p[5] * h) if curved else None,
        'gamma_MHz': float(1.0 / abs(k)) if curved else None,
        'radius_V': float(s / (2 * abs(k))) if curved else None,
        'speed_V_per_MHz': s,
        'P0_V': [float(p[0]), float(p[1])],
        'k_per_MHz': k,
        'f0_fit_MHz': float(fc + p[5] * h),
        'residual_rms_V': rms,
        'residual_rel': rms / span,
        'n_bins': int(len(f)),
        'success': bool(best.status > 0),
        'message': str(best.message),
    }


def trace_curve(trace, freqs_MHz):
    """The fitted trace at ``freqs_MHz`` (complex V), for plotting."""
    du = np.asarray(freqs_MHz, dtype=float) - trace['f0_fit_MHz']
    p0 = trace['P0_V'][0] + 1j * trace['P0_V'][1]
    th = np.radians(trace['theta0_deg'])
    return p0 + 1j * np.exp(1j * th) * trace['speed_V_per_MHz'] * du / (1.0 - 1j * trace['k_per_MHz'] * du)


def _wrap180(x):
    return (np.asarray(x, dtype=float) + 180.0) % 360.0 - 180.0


def target_angles(theta0_deg, hand_deg):
    """Target phase (deg, in the Real tune's frame) for each tune.

    Args:
        theta0_deg: absorptive direction (fit_trace's theta_ref_deg)
        hand_deg: {angle: measured phase of the operator's tune}; must contain 0 and 90 if 180/270 are present

    Returns:
        {angle: target phase}, each unwrapped to lie within 180 deg of the hand tune's phase
    """
    out = {}
    hand = {int(a): float(v) for a, v in hand_deg.items()}
    zero = None
    if 0 in hand:
        c = [theta0_deg, theta0_deg + 180.0]
        zero = min(c, key=lambda t: abs(_wrap180(t - hand[0])))
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
    out['trace'] = trace
    if not trace.get('success'):
        out['message'] = f"trace fit failed: {trace.get('message')}"
        return out
    table = fit['phi_table']
    lev = np.asarray(table['vout'])
    phi = np.asarray(table['phi_deg'])
    hand = {a: float(np.interp(v, lev, phi)) for a, v in centres.items()}
    targets = target_angles(trace['theta_ref_deg'], hand)
    half = max(abs(d) for d in cfg['offsets']) + 1e-6
    converged = True
    for angle, target in targets.items():
        c = float(centres[angle])
        near = np.abs(lev - c) <= half
        vout, inside = solve_dac(lev[near], phi[near], target, c)
        vout = float(np.clip(vout, v_range[0], v_range[1]))
        converged &= inside
        out['tunes'][str(angle)] = {
            'from_vout': c, 'to_vout': round(vout, 5), 'inside': inside,
            'hand_phase_deg': hand[angle], 'target_phase_deg': float(target),
            'moved_deg': float(target - hand[angle]),
            'gain_ratio': calfit.gain_at(fit, vout),
        }
    out['converged'] = bool(converged)
    out['success'] = True
    return out
