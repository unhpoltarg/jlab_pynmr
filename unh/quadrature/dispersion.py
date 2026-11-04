"""Background subtraction for dispersive records (90/270 deg): a polynomial fitted jointly with the
Kramers-Kronig transform of the absorption. Pure numpy.

Why. JLab's subtraction fits a polynomial to the wings and subtracts it. That suits the absorption, which is
small in the wings. The dispersion falls off only as 1/(f - f_L), so its tails reach the window edges and a
wing fit takes part of them as background, leaving distorted wings in Fit Subtracted. In the 2026-10-27 hall
data a cubic wing fit ate the dispersion tails, while a cubic fitted jointly with KK(absorption) over the whole
sweep left a dispersion that matched KK(absorption) to the noise.

Model for a dispersive record's baseline-subtracted sweep y(f):

    y(f) = sum_j c_j x^j + s H[A](f),    x = (f - f_mid) / half-width

A is the absorption from the latest 0 deg record (averaged with -1 x the latest 180 deg record when there is
one), H its Hilbert transform (the KK dispersion up to sign and scale), and s a free scale: the detector gain
ratio and the unobservable sign of 90 deg both go into it. Only the polynomial is subtracted, so Fit Subtracted
keeps the whole measured dispersion; s H[A] is kept on the record for plotting and checks.
"""
import numpy as np


def hilbert(y):
    """Hilbert transform of y on a uniform grid, zero-padded to twice its length (as in the hall analysis)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    Y = np.fft.fft(np.r_[y, np.zeros(n)])
    h = np.zeros(2 * n)
    h[0] = 1.0
    h[1:n] = 2.0
    h[n] = 1.0
    return np.imag(np.fft.ifft(Y * h))[:n]


def joint_kk_fit(freqs, y, absorption, order=3, edge=3):
    """Fit y = polynomial + s * H[absorption] over the sweep, leaving ``edge`` points out at each end.

    Returns:
        (background, kk_curve, scale): background = the polynomial (subtract it), kk_curve = s * H[absorption]
    """
    f = np.asarray(freqs, dtype=float)
    y = np.asarray(y, dtype=float)
    a = np.asarray(absorption, dtype=float)
    if not (len(f) == len(y) == len(a)) or len(f) < 2 * edge + order + 3:
        raise ValueError('sweep, absorption and frequency list must have the same length')
    x = (f - 0.5 * (f.min() + f.max())) / max(0.5 * np.ptp(f), 1e-12)
    X = np.column_stack([x ** j for j in range(int(order) + 1)])
    H = hilbert(a)
    keep = np.zeros(len(f), dtype=bool)
    keep[edge:len(f) - edge] = True
    coef, *_ = np.linalg.lstsq(np.column_stack([X, H])[keep], y[keep], rcond=None)
    return X @ coef[:-1], coef[-1] * H, float(coef[-1])


def make_sub(jlab_sub, absorption, order=3, edge=3, log=None):
    """A sub_method for AnalThread: joint KK fit for this record, JLab's subtraction if that fails.

    The absorption array is captured here, on the GUI thread, so the analysis thread never reads shared state.
    """
    absorption = np.array(absorption, dtype=float)

    def sub(event):
        try:
            background, kk, scale = joint_kk_fit(event.scan.freq_list, event.basesub, absorption, order, edge)
        except Exception as e:
            if log is not None:
                log.warning(f'Joint KK background failed ({e}); using the wing fit for this record.')
            event.quad_sub_method = f'wings (joint KK failed: {e})'
            return jlab_sub(event)
        event.quad_sub_method = 'joint KK'
        event.quad_kk_scale = scale
        event.quad_kk_curve = kk
        return background, np.asarray(event.basesub, dtype=float) - background
    return sub
