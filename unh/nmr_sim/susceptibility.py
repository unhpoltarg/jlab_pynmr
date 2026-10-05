"""Complex RF susceptibility of the deuteron sample, built from the Dulya lineshape.

Convention (engineering time dependence e^{+i w t}, Abragam sign):
    chi(f) = chi'(f) - i chi''(f),   chi'' > 0 is absorption for P > 0.
Kramers-Kronig with this convention: chi' = -H[chi''], where H is the Hilbert
transform along increasing frequency (scipy.signal.hilbert imaginary part).

The ported model's absorptive curve A(f) and dispersive curve D(f) satisfy
D = -H[A] (checked numerically: correlation 0.99999 for ND3 and d-butanol at
P = +-0.3; see tests/test_lineshape.py::test_kramers_kronig_sign). So
    chi_eff(f) = 4 pi eta chi(f) = k * (DISPERSION_SIGN * D(f) - i A(f)),
with DISPERSION_SIGN = +1. eta is the coil filling factor; k folds 4 pi eta,
the spin density and the static susceptibility into one dimensionless
coupling, which nmr_sim calibrates from a target signal size (see qmeter).
"""

from collections import OrderedDict

import numpy as np

from .lineshape import FastModel, MATERIALS, r_of_P

# Fixed by the Kramers-Kronig test; do not change without re-running it.
DISPERSION_SIGN = 1.0

_CACHE_SIZE = 8


def resolve_material(material):
    """Return a lineshape-constants dict for a preset name or a custom dict.

    Args:
        material: key of ``lineshape.MATERIALS`` or a dict with "model"
            ("single"/"double"), "omegQ1" [MHz], "A1", "eta1" and, for
            double, "omegQ2" [MHz], "eta2", "K".
    """
    if isinstance(material, str):
        if material not in MATERIALS:
            raise ValueError(f"Unknown material preset {material!r}; "
                             f"choose from {sorted(MATERIALS)} or give a dict")
        return dict(MATERIALS[material])
    m = dict(material)
    need = ["model", "omegQ1", "A1", "eta1"]
    if m.get("model") == "double":
        need += ["omegQ2", "eta2", "K"]
    missing = [k for k in need if k not in m]
    if missing:
        raise ValueError(f"Custom material missing keys {missing}")
    return m


class Susceptibility:
    """chi_eff(f) = 4 pi eta chi(f) for a deuteron sample.

    Args:
        material: preset name or constants dict (see ``resolve_material``)
        coupling: k, dimensionless scale applied to the 1/MHz lineshape
            curves (so k has units of MHz; chi_eff is dimensionless)
    """

    def __init__(self, material, coupling=1.0):
        self.material = resolve_material(material)
        self.coupling = float(coupling)
        self._models = OrderedDict()

    def _model(self, freq_MHz, larmor_MHz):
        key = (freq_MHz.tobytes(), float(larmor_MHz))
        fm = self._models.get(key)
        if fm is None:
            const = dict(self.material, omegD=float(larmor_MHz))
            fm = FastModel(freq_MHz, const, self.material["model"])
            self._models[key] = fm
            if len(self._models) > _CACHE_SIZE:
                self._models.popitem(last=False)
        else:
            self._models.move_to_end(key)
        return fm

    def parts(self, freq_MHz, larmor_MHz, P):
        """(A, D): absorptive and dispersive lineshape at polarization P.

        Args:
            freq_MHz: frequency grid, MHz
            larmor_MHz: deuteron Larmor frequency, MHz
            P: vector polarization, fraction (|P| < 1)
        Returns:
            two arrays in 1/MHz (before the coupling k)
        """
        freq_MHz = np.ascontiguousarray(freq_MHz, dtype=float)
        if P == 0.0:
            z = np.zeros_like(freq_MHz)
            return z, z.copy()
        return self._model(freq_MHz, larmor_MHz).parts(r_of_P(P))

    def chi_eff(self, freq_MHz, larmor_MHz, P, coupling=None):
        """Complex 4 pi eta chi on ``freq_MHz`` (dimensionless).

        Args:
            freq_MHz: frequency grid, MHz
            larmor_MHz: deuteron Larmor frequency, MHz
            P: vector polarization, fraction
            coupling: override k (default: self.coupling)
        """
        k = self.coupling if coupling is None else coupling
        A, D = self.parts(freq_MHz, larmor_MHz, P)
        return k * (DISPERSION_SIGN * D - 1j * A)
