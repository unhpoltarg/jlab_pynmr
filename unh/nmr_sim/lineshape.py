"""Deuteron NMR lineshape (Dulya spin-1 model), ported for the nmr_sim simulator.

PROVENANCE
    Source : optimized-mcclellan-fits/fitter/deuteron_model.py
             (UNH Polarized Target group; sibling repo of this one)
    Commit : 0f4b4a85b2538793d8d3d947f0eaca31edddf10c  (last commit touching the file)
    Repo HEAD at port time: 95070b73521c5cfac1c2c328ac752b4e23968174
    Ported : 2026-10-05

    Ported verbatim (numerics unchanged): _phi_grid, _half_absorptive,
    _half_dispersive, _phi_average (incl. the J=64 / (J+1) normalisation quirk),
    Xi, ratio_P, ratio_Q, bonds, FastModel (normal phi grid only: __init__,
    _branches, _components, real, components), MATERIALS.

    New in this port (not in the source):
      * r_of_P(P)              closed-form inverse of ratio_P
      * FastModel.parts(r)     absorptive and dispersive curves returned separately
      * FastModel.__init__ no longer precomputes the branch-swapped ("rev") grid

    Omitted (TODO, needed for hole burning): phi_avg_*_rev, _fit_*_rev,
    component_signed_rev, bump_component, FastModel._components_rev / real_rev /
    bump / bump_components, the non-Boltzmann (frequency-hopping) variants, and
    the area-method helpers.

Physics reference: C. Dulya et al., "A line-shape analysis for spin-1 NMR
signals", NIM A 398 (1997) 109; source repo documentation/ComplexDeut.tex and
documentation/Dissertation.pdf.

Units: every frequency (freq, omegD, omegQ) is in MHz. A, eta, r, K, scale are
dimensionless. Curves carry an overall 1/omegQ (1/MHz) normalisation.

IMPORTANT preserved quirk (do NOT "fix"): the phi sum has J=64 terms but is
divided by (J+1)=65. The offset is absorbed into ``scale``/Xi upstream.
"""

import numpy as np

# Number of phi samples in the powder-pattern average (0 -> pi/2). Kept at 64,
# and the average is divided by (J + 1) to match the source exactly.
_J = 64

# Xi(r) quartic-correction coefficients (source: deuts.Xi fit-path values).
_XI_A = -0.38616
_XI_B = -0.60995


# ---------------------------------------------------------------------------
# Single spin-flip curves (one quadrupole angle phi)
# ---------------------------------------------------------------------------
def _phi_grid():
    """Phi samples on [0, pi/2), shape (J,), in radians."""
    return (np.pi / 2.0) * np.arange(_J) / _J


def _half_absorptive(freq, epsi, omegD, omegQ, A, eta, phi):
    """Absorptive single spin-flip curve, Dulya Eq. 14.

    freq, omegD, omegQ in MHz; ``freq`` shape (nfreq,), ``phi`` shape (J, 1);
    returns (J, nfreq), dimensionless.
    """
    R = (freq - omegD) / (3.0 * omegQ)
    base = 1.0 - epsi * R - eta * np.cos(2.0 * phi)
    rhosq = np.sqrt(A ** 2 + base ** 2)           # note: "rhosq" is sqrt already
    rho = np.sqrt(rhosq)                          # (matches source naming)
    alpha = np.arccos(base / rhosq)
    Y = np.sqrt(3.0 - eta * np.cos(2.0 * phi))
    a2 = alpha / 2.0
    left = 2.0 * np.cos(a2) * (
        np.arctan((Y ** 2 - rhosq) / (2.0 * Y * rho * np.sin(a2))) + np.pi / 2.0)
    num = Y ** 2 + rhosq + 2.0 * Y * rho * np.cos(a2)
    den = Y ** 2 + rhosq - 2.0 * Y * rho * np.cos(a2)
    right = np.sin(a2) * np.log(num / den)
    return (1.0 / (2.0 * np.pi * rho)) * (left + right)


def _half_dispersive(freq, epsi, omegD, omegQ, A, eta, phi):
    """Dispersive single spin-flip curve (source: deuts.deut_disp_half).

    Same arguments/units as ``_half_absorptive``.
    """
    R = (freq - omegD) / (3.0 * omegQ)
    base = 1.0 - epsi * R - eta * np.cos(2.0 * phi)
    rhosq = np.sqrt(A ** 2 + base ** 2)
    rho = np.sqrt(rhosq)
    alpha = np.arccos(base / rhosq)
    Y = np.sqrt(3.0 - eta * np.cos(2.0 * phi))
    a2 = alpha / 2.0
    left = 2.0 * np.sin(a2) * (
        np.arctan((Y ** 2 - rhosq) / (2.0 * Y * rho * np.sin(a2))) + np.pi / 2.0)
    num = Y ** 2 + rhosq + 2.0 * Y * rho * np.cos(a2)
    den = Y ** 2 + rhosq - 2.0 * Y * rho * np.cos(a2)
    right = np.cos(a2) * np.log(den / num)
    return (1.0 / (2.0 * np.pi * rho)) * (left + right)


def _phi_average(freq, epsi, omegD, omegQ, A, eta, half_fn, phi):
    """Powder-pattern average of a half-curve over the phi samples (J=64, /65)."""
    freq = np.asarray(freq, dtype=float)
    num = np.sqrt(3.0) * half_fn(freq, epsi, omegD, omegQ, A, eta, phi)
    den = np.sqrt(3.0 - eta * np.cos(2.0 * phi))
    avgtot = np.sum(num / den, axis=0)
    return avgtot / (_J + 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def Xi(r):
    """Quartic Xi(r) scaling correction (dimensionless), source deuts.Xi."""
    Pz = ratio_P(r)
    return _XI_A * Pz ** 4 + _XI_B * Pz ** 2 + 1.0


def ratio_P(r):
    """Vector polarization P (fraction) from the asymmetry r = p(+1)/p(0) = p(0)/p(-1)."""
    return (r * r - 1.0) / (r * r + r + 1.0)


def ratio_Q(r):
    """Tensor polarization Q (fraction) from the asymmetry r.

    Assumes a single spin temperature (Boltzmann populations).
    """
    return (r * r - 2.0 * r + 1.0) / (r * r + r + 1.0)


def r_of_P(P):
    """Inverse of ``ratio_P``: asymmetry r for vector polarization P (fraction).

    NEW in this port. Solves (1-P) r^2 - P r - (1+P) = 0 for the positive root:
        r = (P + sqrt(4 - 3 P^2)) / (2 (1 - P)),
    valid for -1 < P < 1 (r -> 0 as P -> -1, r = 1 at P = 0).
    Assumes a single spin temperature.
    """
    P = np.asarray(P, dtype=float)
    if np.any(np.abs(P) >= 1.0):
        raise ValueError(f"P must satisfy |P| < 1, got {P}")
    out = (P + np.sqrt(4.0 - 3.0 * P ** 2)) / (2.0 * (1.0 - P))
    return float(out) if out.ndim == 0 else out


def bonds(model, omegQ1, omegQ2, A1, eta1, eta2, K):
    """List of (omegQ [MHz], A, eta, k, label) per bond for the chosen model.

    k is the bond weight: single -> 1.0; double -> (1-K) carbon, K oxygen.
    A2 is pegged via A2 = A1*omegQ1/omegQ2.
    """
    if model == "single":
        return [(omegQ1, A1, eta1, 1.0, "X")]
    A2 = A1 * omegQ1 / omegQ2
    return [(omegQ1, A1, eta1, 1.0 - K, "C"), (omegQ2, A2, eta2, K, "O")]


# ---------------------------------------------------------------------------
# Fast model: precomputed phi-averages, free (r, scale, phase)
# ---------------------------------------------------------------------------
class FastModel:
    """Precomputed Dulya lineshape on a fixed frequency grid.

    Args:
        freqs: frequency grid, MHz
        const: dict with omegD [MHz], omegQ1 [MHz], A1, eta1 and, for the
            double model, omegQ2 [MHz], eta2, K
        model: "single" or "double"
    """

    def __init__(self, freqs, const, model="double"):
        self.freqs = np.asarray(freqs, dtype=float)
        self.const = dict(const)
        self.model = model
        self.omegD = const["omegD"]
        self._bonds = bonds(model, const["omegQ1"], const.get("omegQ2", 0.0),
                            const["A1"], const["eta1"], const.get("eta2", 0.0),
                            const.get("K", 0.0))
        self._pre = []
        grid = _phi_grid()[:, None]
        for omegQ, A, eta, k, label in self._bonds:
            R = (self.freqs - self.omegD) / (3.0 * omegQ)
            theta = omegQ / self.omegD
            base = {}
            for epsi in (-1, 1):
                base[("abs", epsi)] = _phi_average(
                    self.freqs, epsi, self.omegD, omegQ, A, eta, _half_absorptive, grid) / omegQ
                base[("disp", epsi)] = _phi_average(
                    self.freqs, epsi, self.omegD, omegQ, A, eta, _half_dispersive, grid) / omegQ
            self._pre.append(dict(R=R, theta=theta, k=k, label=label, base=base))

    def _branches(self, r, R, theta):
        pos = (r ** 2 - r ** (1 - 3 * theta * R)) / (r ** (1 - theta * R))
        neg = (r ** (1 + 3 * theta * R) - 1) / (r ** (1 + theta * R))
        return neg, pos

    def _components(self, r, scale, phase):
        """Dict (label, epsi) -> component curve (with Xi, scale, k); phase in rad."""
        xi = Xi(r)
        cphase, sphase = np.cos(phase), np.sin(phase)
        comps = {}
        for pre in self._pre:
            neg, pos = self._branches(r, pre["R"], pre["theta"])
            b = pre["base"]
            for epsi, branch, dsign in ((-1, neg, 1.0), (1, pos, -1.0)):
                absorptive = b[("abs", epsi)] * branch
                dispersive = dsign * b[("disp", epsi)] * branch
                comps[(pre["label"], epsi)] = (
                    xi * scale * pre["k"] * (absorptive * cphase + dispersive * sphase))
        return comps

    def real(self, r, scale, phase):
        """Real lineshape (with Xi): absorptive*cos(phase) + dispersive*sin(phase)."""
        return sum(self._components(r, scale, phase).values())

    def components(self, r, scale, phase):
        """Public access to the per-(label, epsi) component curves."""
        return self._components(r, scale, phase)

    def parts(self, r):
        """NEW in this port: (absorptive, dispersive) curves at scale 1, with Xi(r).

        Equivalent to (real(r, 1, 0), real(r, 1, pi/2)) without the cos/sin
        round-off. Units 1/MHz (from the 1/omegQ normalisation).
        """
        xi = Xi(r)
        absorptive = np.zeros_like(self.freqs)
        dispersive = np.zeros_like(self.freqs)
        for pre in self._pre:
            neg, pos = self._branches(r, pre["R"], pre["theta"])
            b = pre["base"]
            for epsi, branch, dsign in ((-1, neg, 1.0), (1, pos, -1.0)):
                absorptive = absorptive + pre["k"] * b[("abs", epsi)] * branch
                dispersive = dispersive + pre["k"] * dsign * b[("disp", epsi)] * branch
        return xi * absorptive, xi * dispersive


# ---------------------------------------------------------------------------
# Material presets (Dissertation Tables 5.2-5.11), copied verbatim.
# phase stored in degrees. nmr_sim uses only the shape constants (omegQ*, A1,
# eta*, K, model); omegD comes from the simulated field, amplitude from the
# Q-meter calibration, and phase from the Q-meter reference phase.
# ---------------------------------------------------------------------------
MATERIALS = {
    "irradiated d-butanol (Dec 2025, 12th)": {
        "model": "double", "omegD": 33.181728, "omegQ1": 0.021701,
        "omegQ2": 0.026312, "A1": 0.025862, "eta1": 0.036178, "eta2": 0.168391,
        "K": 0.054466, "scale": 0.004037, "phase_deg": 6.41,
    },
    "irradiated d-butanol (Dec 2025, 13th/15th)": {
        "model": "double", "omegD": 33.181266, "omegQ1": 0.021701,
        "omegQ2": 0.026227, "A1": 0.025472, "eta1": 0.036356, "eta2": 0.170048,
        "K": 0.058355, "scale": 0.004423, "phase_deg": 5.78,
    },
    "trityl-doped d-propanediol (Oct 2021)": {
        "model": "double", "omegD": 33.051328, "omegQ1": 0.021720,
        "omegQ2": 0.025991, "A1": 0.028222, "eta1": 0.062230, "eta2": 0.196132,
        "K": 0.218579, "scale": 0.000296, "phase_deg": 2.16,
    },
    "deuterated ammonia (Dec 2024)": {
        "model": "single", "omegD": 32.450724, "omegQ1": 0.027335,
        "A1": 0.038029, "eta1": 0.116228, "scale": 0.001189, "phase_deg": 0.72,
    },
}
