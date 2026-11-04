"""Phase-DAC calibration: the step plan and the fits. Pure numpy/scipy, no Qt or hardware.

Model. At calibration step k the phase DAC is at v_k (time t_k), and the phase output, averaged into
frequency bins j, is

    y_kj = g_k d_k [Re W_j cos phi_k + Im W_j sin phi_k] + offset(u_k) ,     u_k = v_k - v_real

    phi_k   free at each distinct DAC value    reference-phase shift relative to the Real tune (phi(v_real) = 0)
    g_k     = 1 + sum_n gain_n u_k^n           detector gain relative to the Real tune (low order)
    d_k     = 1 + drift tau_k                  slow signal drift during the calibration, tau in [-0.5, 0.5]
    offset  = sum_n offset_n u^n               detector DC offset (low order)

W_j is the complex response (Q-curve plus any NMR line) in bin j at the Real tune. It is unknown and is
solved for linearly, together with the offset, at each trial of the nonlinear parameters (variable
projection). The phase is given no shape, because the Mini-Circuits shifters are strongly S-shaped
(SCPHS-51+: about 10 deg/V near 0 V, 75 deg/V near 8 V). A smooth polynomial misses them by degrees.

Limits of what projections can tell (also in notes/quadrature_phase_design.md):
- The sign of the rotation is not observable: phi -> -phi with W -> conj(W) gives identical data. The fit
  reports phi increasing with v. The offline complex lineshape fit, using the Kramers-Kronig relation
  between the two quadratures, fixes the sign.
- More generally, projections fix the reference direction only up to a 2x2 linear map. A 90 deg angle
  therefore can't be measured without a metric assumption. Here the assumption is that the gain is a
  low-order polynomial in v. 0 and 180 deg (antiparallel) don't depend on it. How far the assumption
  holds depends on the real shifter's gain variation (SCPHS-51+: about a 0.8 dB insertion-loss swing at
  32.7 MHz, partly passed on to the mixer).
"""
import numpy as np
from scipy import optimize


def step_plan(cal, v_real, other_tunes=()):
    """The calibration steps, in the order they are taken.

    Args:
        cal: the 'cal' settings dict (v_min, v_max, steps, passes, ref_every)
        v_real: the Real (0 deg) Phase Tune, 0..1
        other_tunes: the operator's other tunes (Imag, ...). Each is measured as its own step in each
            pass, so its angle is measured directly rather than interpolated.

    Returns:
        list of dicts {vout, pass, kind}: kind 'grid' for scan points, 'tune' for the other tunes, 'ref' for
        returns to v_real. The first and last steps are 'ref'.
    """
    grid = np.linspace(float(cal['v_min']), float(cal['v_max']), int(cal['steps']))
    extra = {round(float(t), 6) for t in other_tunes if t is not None} - {round(float(v_real), 6)}
    grid = np.array(sorted(set(np.round(grid, 6)) | extra))
    passes = [grid] if int(cal['passes']) == 1 else [grid, grid[::-1]]
    ref_every = int(cal.get('ref_every', 0) or 0)
    plan = [{'vout': float(v_real), 'pass': 0, 'kind': 'ref'}]
    n = 0
    for p, values in enumerate(passes, start=1):
        for v in values:
            kind = 'tune' if round(float(v), 6) in extra else 'grid'
            plan.append({'vout': float(v), 'pass': p, 'kind': kind})
            n += 1
            if ref_every and n % ref_every == 0:
                plan.append({'vout': float(v_real), 'pass': p, 'kind': 'ref'})
    if plan[-1]['kind'] != 'ref':
        plan.append({'vout': float(v_real), 'pass': len(passes), 'kind': 'ref'})
    return plan


def bin_sweep(values, bins):
    """Average a sweep into ``bins`` nearly equal contiguous bins."""
    values = np.asarray(values, dtype=float)
    bins = max(1, min(int(bins), len(values)))
    return np.array([chunk.mean() for chunk in np.array_split(values, bins)])


class _Model:
    """Variable-projection model. Nonlinear parameters: the phase at each distinct DAC value except the Real
    tune (fixed at 0), the gain polynomial and the drift. Linear: W_j, and the offset polynomial."""

    def __init__(self, v, v_real, tau, Y, gain_order, offset_order, fit_drift):
        self.Y = Y
        self.K, self.J = Y.shape
        self.u = v - v_real
        self.tau = tau
        key = np.round(v, 6)
        self.levels, self.level_of = np.unique(key, return_inverse=True)
        self.real_level = int(np.argmin(np.abs(self.levels - round(v_real, 6))))
        if abs(self.levels[self.real_level] - round(v_real, 6)) > 1e-6:
            raise ValueError('the Real tune must be one of the calibration steps')
        self.free_levels = [i for i in range(len(self.levels)) if i != self.real_level]
        self.gain_order, self.offset_order, self.fit_drift = int(gain_order), int(offset_order), bool(fit_drift)
        self.names = [f'phi@{self.levels[i]:.6f}' for i in self.free_levels]
        self.names += [f'gain{n}' for n in range(1, self.gain_order + 1)]
        if self.fit_drift:
            self.names.append('drift')

    def unpack(self, x):
        nf = len(self.free_levels)
        phi_level = np.zeros(len(self.levels))
        phi_level[self.free_levels] = x[:nf]
        gain = np.asarray(x[nf:nf + self.gain_order])
        drift = x[nf + self.gain_order] if self.fit_drift else 0.0
        return phi_level, gain, drift

    def gain_of(self, gain, u):
        u = np.asarray(u, dtype=float)
        return 1.0 + sum(g * u ** (n + 1) for n, g in enumerate(gain))

    def design(self, x):
        phi_level, gain, drift = self.unpack(x)
        phi = phi_level[self.level_of]
        amp = self.gain_of(gain, self.u) * (1.0 + drift * self.tau)
        K, J = self.K, self.J
        ncol = 2 * J + 1 + self.offset_order
        A = np.zeros((K * J, ncol))
        rows = np.arange(K * J)
        jj = np.tile(np.arange(J), K)
        kk = np.repeat(np.arange(K), J)
        A[rows, jj] = amp[kk] * np.cos(phi[kk])
        A[rows, J + jj] = amp[kk] * np.sin(phi[kk])
        A[:, 2 * J] = 1.0
        for n in range(1, self.offset_order + 1):
            A[:, 2 * J + n] = self.u[kk] ** n
        return A

    def solve(self, x):
        A = self.design(x)
        y = self.Y.reshape(-1)
        lin, *_ = np.linalg.lstsq(A, y, rcond=None)
        return lin, y - A @ lin

    def residual(self, x):
        return self.solve(x)[1]


def _start_phases(model):
    """Starting phases: a smooth (polynomial) phase map, from a coarse slope scan then a short fit."""
    u_lev = model.levels - model.levels[model.real_level]
    order = int(min(7, max(1, len(model.levels) - 3)))
    rest = np.zeros(model.gain_order + (1 if model.fit_drift else 0))

    def x_of(c):
        phi = sum(cn * u_lev ** (n + 1) for n, cn in enumerate(c))
        return np.r_[phi[model.free_levels], rest]

    span = max(np.ptp(u_lev), 1e-6)
    best = None
    for total_deg in np.concatenate([np.linspace(5, 90, 18), np.linspace(100, 1080, 50)]):
        c = np.r_[np.radians(total_deg) / span, np.zeros(order - 1)]
        cost = np.sum(model.residual(x_of(c)) ** 2)
        if best is None or cost < best[0]:
            best = (cost, c)
    res = optimize.least_squares(lambda c: model.residual(x_of(c)), best[1], method='lm', max_nfev=4000)
    return x_of(res.x)


def fit_calibration(vouts, times_s, sweeps, v_real, tunes=None, gain_order=2, offset_order=1, fit_drift=True,
                    bins=32, v_range=None):
    """Fit the phase-DAC map from calibration steps.

    The phase at each distinct DAC value is a free parameter (no assumed shape). The gain and offset are
    low-order polynomials in v, and W (the response at the Real tune) is free in every frequency bin.

    Args:
        vouts: phase-DAC value at each step (0..1); must include v_real
        times_s: time of each step, s (any origin)
        sweeps: phase output at each step, one array per step (V), all the same length
        v_real: the Real (0 deg) Phase Tune; phi and gain are relative to it
        tunes: {angle: vout} of the operator's tunes, reported at their fitted angles
        gain_order, offset_order: polynomial orders in v of the gain change and the offset (0 = constant)
        fit_drift: fit a linear drift of the signal with time
        bins: frequency bins the sweeps are averaged into
        v_range: (v_min, v_max) for the suggestions (default: the stepped range)

    Returns:
        dict (JSON-ready): phase at each DAC value with uncertainties, the angle and gain of each tune,
        suggested DAC values for +-90/180/270 deg, gain and offset coefficients, and fit quality
    """
    vouts = np.asarray(vouts, dtype=float)
    times_s = np.asarray(times_s, dtype=float)
    Y = np.array([bin_sweep(s, bins) for s in sweeps])
    T = max(np.ptp(times_s), 1e-9)
    tau = (times_s - times_s.min()) / T - 0.5
    model = _Model(vouts, float(v_real), tau, Y, gain_order, offset_order, fit_drift)

    x0 = _start_phases(model)
    res = optimize.least_squares(model.residual, x0, method='trf', x_scale='jac', max_nfev=200)
    x = res.x.copy()
    nf = len(model.free_levels)
    phi_level, gain, drift = model.unpack(x)
    # Each level's phase is only defined modulo 360 deg; unwrap along v (grid steps are far below 180 deg)
    phi_un = np.unwrap(phi_level)
    phi_un -= phi_un[model.real_level]
    # sign convention: phi increases with v (the sign is not observable; see the module docstring)
    slope = np.polyfit(model.levels, phi_un, 1)[0] if len(model.levels) > 1 else 1.0
    flip = np.ones(len(x))
    if slope < 0:
        flip[:nf] = -1
        x = x * flip
        phi_un = -phi_un
    phi_level, gain, drift = model.unpack(x)
    phi_level = phi_un
    lin, r = model.solve(x)
    dof = max(1, r.size - len(x) - lin.size)
    s2 = float(np.sum(r ** 2) / dof)
    try:
        J = res.jac
        cov = np.linalg.pinv(J.T @ J) * s2 * np.outer(flip, flip)
    except Exception:
        cov = np.full((len(x), len(x)), np.nan)
    phi_err = np.zeros(len(model.levels))
    phi_err[model.free_levels] = np.sqrt(np.clip(np.diag(cov)[:nf], 0, None))

    levels = model.levels
    phi_deg = np.degrees(phi_level)
    lo, hi = v_range if v_range is not None else (levels.min(), levels.max())
    # Where the shifter stops responding (the JLab box's control voltage clips near 80 % DAC): a run of at
    # least two top-end steps whose sweeps differ by < 0.2 % of the signal. Judged on the data, because the
    # fit's angles can creep there (gain and offset absorb it). Monotonic and suggestions use the part below.
    Ylev = np.array([model.Y[model.level_of == i].mean(axis=0) for i in range(len(levels))])
    scale = max(np.max(np.abs(Ylev - Ylev.mean())), 1e-12)
    step_change = np.max(np.abs(np.diff(Ylev, axis=0)), axis=1) / scale
    n_flat = 0
    while n_flat < len(step_change) and step_change[len(step_change) - 1 - n_flat] < 2e-3:
        n_flat += 1
    clip_vout = float(levels[len(levels) - 1 - n_flat]) if n_flat >= 2 else None
    live = slice(0, len(levels) - n_flat) if n_flat >= 2 else slice(None)
    dlive = np.diff(phi_deg[live])
    monotonic = bool(np.all(dlive > 0) or np.all(dlive < 0))
    if clip_vout is not None:
        hi = min(hi, clip_vout)

    def gain_at_v(v):
        return float(model.gain_of(gain, float(v) - float(v_real)))

    tune_report = {}
    for angle, v in (tunes or {}).items():
        if v is None:
            continue
        i = int(np.argmin(np.abs(levels - v)))
        measured = abs(levels[i] - v) < 1e-6
        tune_report[str(angle)] = {
            'vout': float(v),
            'angle_deg': float(phi_deg[i]) if measured else float(np.interp(v, levels, phi_deg)),
            'angle_err_deg': float(np.degrees(phi_err[i])) if measured else None,
            'measured_step': bool(measured),
            'gain_ratio': gain_at_v(v),
            'in_range': bool(levels.min() - 1e-9 <= v <= levels.max() + 1e-9),
        }

    dense_v = np.linspace(lo, hi, 20001)
    dense_phi = np.interp(dense_v, levels, phi_deg)
    suggested = {}
    for target in (90, -90, 180, -180, 270, -270):
        hit = np.nonzero(np.diff(np.sign(dense_phi - target)))[0]
        if hit.size:
            i = hit[np.argmin(np.abs(dense_v[hit] - v_real))]       # crossing nearest the Real tune
            v0, v1, p0, p1 = dense_v[i], dense_v[i + 1], dense_phi[i], dense_phi[i + 1]
            suggested[str(target)] = float(v0 + (target - p0) * (v1 - v0) / (p1 - p0))
        else:
            suggested[str(target)] = None

    J_bins = model.J
    W = lin[:J_bins] + 1j * lin[J_bins:2 * J_bins]
    gerr = np.sqrt(np.clip(np.diag(cov)[nf:nf + model.gain_order], 0, None))
    return {
        'model': 'y_kj = g(v_k)(1 + drift tau_k)[Re W_j cos phi_k + Im W_j sin phi_k] + offset(v_k);'
                 ' phi free at each distinct v (phi(v_real) = 0); g = 1 + sum gain_n u^n;'
                 ' offset = sum offset_n u^n; u = v - v_real',
        'v_real': float(v_real),
        'gain_order': model.gain_order, 'offset_order': model.offset_order, 'fit_drift': model.fit_drift,
        'bins': J_bins,
        'phi_table': {'vout': levels.tolist(), 'phi_deg': phi_deg.tolist(),
                      'phi_err_deg': np.degrees(phi_err).tolist()},
        'gain_coeffs': gain.tolist(), 'gain_coeffs_err': gerr.tolist(),
        'drift': float(drift),
        'offset_coeffs_V': lin[2 * J_bins:].tolist(),
        'W_abs_V': np.abs(W).tolist(),
        'W_angle_deg': np.degrees(np.angle(W)).tolist(),
        'chi2_per_dof_V2': s2,
        'residual_rms_V': float(np.sqrt(np.mean(r ** 2))),
        'n_steps': int(len(vouts)),
        'success': bool(res.status > 0),
        'message': str(res.message),
        'range_deg': float(abs(phi_deg.max() - phi_deg.min())),
        'clip_vout': clip_vout,
        'monotonic': monotonic,
        'tunes': tune_report,
        'suggested_vout': suggested,
        'sign_note': 'The sign of the rotation is not observable from projections; phi is reported '
                     'increasing with v. The complex lineshape fit fixes the sign.',
        'metric_note': 'Projections fix the reference direction only up to a 2x2 linear map. Angles here '
                       'assume the detector gain is a low-order polynomial in v (gain_order). 0 and 180 deg '
                       '(antiparallel) do not depend on that assumption; 90 deg does.',
    }


def angle_at(fit, vout):
    """Fitted reference-phase shift (deg) of ``vout`` relative to the fit's Real tune, or None."""
    if not fit or not fit.get('phi_table'):
        return None
    t = fit['phi_table']
    return float(np.interp(float(vout), t['vout'], t['phi_deg']))


def gain_at(fit, vout):
    """Fitted detector gain of ``vout`` relative to the fit's Real tune, or None."""
    if not fit or 'gain_coeffs' not in fit:
        return None
    u = float(vout) - fit['v_real']
    return float(1.0 + sum(g * u ** (n + 1) for n, g in enumerate(fit['gain_coeffs'])))


def settle_fit(t_ms, values):
    """Look for a settling transient in back-to-back chunk means after a DAC jump.

    Args:
        t_ms: time of each chunk after the DAC write, ms (end of the chunk)
        values: mean phase output of each chunk, V

    Returns:
        dict: tau_ms (None if no transient is seen), amplitude_V, noise_V, settled_by_ms (time of the first
        chunk within 3 noise of the final level), first_chunk_ms
    """
    t = np.asarray(t_ms, dtype=float)
    y = np.asarray(values, dtype=float)
    out = {'t_ms': t.tolist(), 'mean_V': y.tolist(), 'tau_ms': None, 'amplitude_V': 0.0,
           'first_chunk_ms': float(t[0]) if t.size else None}
    if t.size < 4:
        out['note'] = 'too few chunks'
        return out
    tail = y[t.size // 2:]
    final, noise = float(np.mean(tail)), float(np.std(tail, ddof=1) if tail.size > 1 else 0.0)
    out['final_V'], out['noise_V'] = final, noise
    dev = np.abs(y - final)
    within = np.nonzero(dev <= 3 * max(noise, 1e-15))[0]
    out['settled_by_ms'] = float(t[within[0]]) if within.size else None
    amp = y[0] - final
    out['amplitude_V'] = float(amp)
    if abs(amp) <= 5 * max(noise, 1e-15):
        out['note'] = 'no transient seen at this chunk spacing'
        return out
    try:
        f = lambda tt, a, tau, c: c + a * np.exp(-(tt - t[0]) / tau)
        p, _ = optimize.curve_fit(f, t, y, p0=[amp, max(1.0, (t[-1] - t[0]) / 4), final], maxfev=10000)
        out['tau_ms'] = float(abs(p[1]))
        out['note'] = 'exponential fit'
    except Exception as e:
        out['note'] = f'fit failed: {e}'
    return out
