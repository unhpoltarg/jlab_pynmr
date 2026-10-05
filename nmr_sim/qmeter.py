"""Constant-current (Liverpool) series Q-meter with a lambda/2 cable.

Reference: G.R. Court et al., "A high precision Q-meter for the measurement of
proton polarization in polarised targets", NIM A 324 (1993) 433.

Circuit (time dependence e^{+i w t}, w = 2 pi f, f in Hz internally):

    U --R_cc--+------------------+---- detector (Z_amp to ground)
              |                  |
           R_damp                |
              |                  |
           C (+ varactor dC)     |
              |                  |
         cable Z0, length l      |
              |                  |
         coil: r_coil + i w L0 (1 + chi_eff)      (other ends to ground)

    Z_L  = r_coil + i w L0 (1 + chi_eff),  chi_eff = 4 pi eta (chi' - i chi'')
    Z_in = Z0 (Z_L + Z0 tanh(gl)) / (Z0 + Z_L tanh(gl)),  g = alpha + i w/(v_f c)
    Z_T  = R_damp + 1/(i w C) + Z_in
    Z_p  = Z_T || Z_amp
    V    = U Z_p / (R_cc + Z_p)               (-> I Z_T when R_cc >> |Z_p|)

Absorption (chi'' > 0) adds w L0 chi_eff'' to the coil resistance, so near
resonance dV/V ~ Q chi_eff''. Outputs:
    phase = G_phase * Re(V exp(-i phi_ref))    phase-sensitive detector
    diode = G_diode * |V|                      diode (magnitude) detector
phi_ref defaults to the phase of the pure-absorption response at the tune
frequency (so the phase output is the absorptive signal), plus a configurable
offset and the Tune-tab phase DAC. G_phase and G_diode are fixed once at
construction so that, tuned and with chi = 0, the outputs at the tune
frequency equal ``phase_bg_V`` and ``diode_bg_V``.

Units: frequencies in MHz at the API, ohms, henries/farads internally
(L0 in uH and C in pF at the API), volts.
"""

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np

C_M_PER_S = 299_792_458.0     # speed of light, m/s
NP_PER_DB = 1.0 / 8.685889638  # nepers per decibel


@dataclass(frozen=True)
class QMeterParams:
    """Q-meter component values. All have defaults; see the README for meaning.

    The defaults are NOT measured UNH values. L0, R_damp and Z_amp were chosen
    to reproduce the Q-curve shape of the replay event utils/d_signal_event.txt
    (diode varies ~1-3 %, phase ~0.1-0.2 % across +-0.4 MHz), which needs a
    heavily damped circuit (coil Q ~ 2). Replace with real values when known.
    """
    U_V: float = 0.6                 # RF drive amplitude, V
    R_cc_ohm: float = 681.0          # constant-current resistor, ohm
    Z_amp_ohm: Optional[float] = None  # detector input impedance, ohm (None = open)
    L0_uH: float = 0.25              # coil inductance, uH
    r_coil_ohm: float = 0.3          # coil series resistance, ohm
    R_damp_ohm: float = 25.0         # damping resistor, ohm
    C_tune_pF: Optional[float] = None  # tuning capacitance, pF (None = auto-tune)
    Z0_ohm: float = 50.0             # cable characteristic impedance, ohm
    v_f: float = 0.66                # cable velocity factor
    loss_dB_per_m: float = 0.05      # cable attenuation at loss_ref_MHz, dB/m
    loss_ref_MHz: Optional[float] = None  # reference freq for loss (None = tune)
    cable_half_waves: int = 1        # cable length in half-wavelengths at tune (0 = none)
    cable_length_m: Optional[float] = None  # explicit cable length, m (overrides half-waves)
    tune_MHz: Optional[float] = None  # tune frequency, MHz (None = centre of sweep)
    varactor_span_pF: float = 2.0    # capacitance change at diode DAC = 1, pF
    phase_dac_span_deg: float = 180.0  # reference-phase change at phase DAC = 1, deg
    ref_phase_offset_deg: float = 0.0  # reference phase relative to absorptive, deg
    phase_bg_V: float = -2.78        # phase output when tuned, chi = 0, at tune freq, V
    diode_bg_V: float = -0.526       # diode output when tuned, chi = 0, at tune freq, V


def omega(freq_MHz):
    """Angular frequency (rad/s) from frequency in MHz."""
    return 2.0 * np.pi * np.asarray(freq_MHz, dtype=float) * 1e6


def coil_impedance(freq_MHz, L0_H, r_coil_ohm, chi_eff=0.0):
    """Coil impedance r + i w L0 (1 + chi_eff), ohm. chi_eff = 4 pi eta chi (complex)."""
    return r_coil_ohm + 1j * omega(freq_MHz) * L0_H * (1.0 + chi_eff)


def cable_input_impedance(Z_load, freq_MHz, Z0_ohm, length_m, v_f, alpha_Np_per_m):
    """Input impedance (ohm) of a lossy line of length ``length_m`` terminated by Z_load.

    Z_in = Z0 (Z_L + Z0 tanh(g l)) / (Z0 + Z_L tanh(g l)), g = alpha + i w/(v_f c).
    ``alpha_Np_per_m`` may be an array matching ``freq_MHz``.
    """
    if length_m == 0:
        return Z_load
    gamma = alpha_Np_per_m + 1j * omega(freq_MHz) / (v_f * C_M_PER_S)
    t = np.tanh(gamma * length_m)
    return Z0_ohm * (Z_load + Z0_ohm * t) / (Z0_ohm + Z_load * t)


def tank_impedance(freq_MHz, Z_in, R_damp_ohm, C_F):
    """Series tank impedance R_damp + 1/(i w C) + Z_in, ohm."""
    return R_damp_ohm + 1.0 / (1j * omega(freq_MHz) * C_F) + Z_in


def node_voltage(Z_T, U_V, R_cc_ohm, Z_amp_ohm):
    """Complex detector-node voltage (V) for drive U through R_cc into Z_T || Z_amp."""
    Z_p = Z_T if Z_amp_ohm is None else Z_T * Z_amp_ohm / (Z_T + Z_amp_ohm)
    return U_V * Z_p / (R_cc_ohm + Z_p)


class QMeter:
    """A tuned Q-meter instance.

    Args:
        params: QMeterParams
        tune_MHz: tune frequency, MHz (used when params.tune_MHz is None)
    """

    def __init__(self, params, tune_MHz):
        self.p = params
        self.f0 = float(params.tune_MHz if params.tune_MHz is not None else tune_MHz)
        p = self.p
        self.L0_H = p.L0_uH * 1e-6
        if p.cable_length_m is not None:
            self.length_m = float(p.cable_length_m)
        else:
            self.length_m = p.cable_half_waves * p.v_f * C_M_PER_S / (2.0 * self.f0 * 1e6)
        self.loss_ref_MHz = p.loss_ref_MHz if p.loss_ref_MHz is not None else self.f0
        self.dC_pF = 0.0
        self.dphi_deg = 0.0
        if p.C_tune_pF is not None:
            self.C_F = p.C_tune_pF * 1e-12
        else:
            Z_in0 = self._z_in(self.f0, 0.0)
            if np.imag(Z_in0) <= 0:
                raise ValueError("Cable + coil is not inductive at the tune frequency; "
                                 "cannot auto-tune a series capacitor (set C_tune_pF).")
            self.C_F = 1.0 / (omega(self.f0) * np.imag(Z_in0))
        # Absorptive reference phase at the tune frequency (DAC = 0, chi = 0).
        eps = 1e-9
        dV = self.voltage(self.f0, -1j * eps) - self.voltage(self.f0, 0.0)
        self.phi_abs = float(np.angle(dV))
        # Detector gains from the tuned, chi = 0 state.
        V0 = self.voltage(self.f0, 0.0)
        self.G_phase = p.phase_bg_V / float(np.real(V0 * np.exp(-1j * self.ref_phase_rad())))
        self.G_diode = p.diode_bg_V / float(np.abs(V0))

    def _alpha(self, freq_MHz):
        a_ref = self.p.loss_dB_per_m * NP_PER_DB
        return a_ref * np.sqrt(np.asarray(freq_MHz, dtype=float) / self.loss_ref_MHz)

    def _z_in(self, freq_MHz, chi_eff):
        Z_L = coil_impedance(freq_MHz, self.L0_H, self.p.r_coil_ohm, chi_eff)
        return cable_input_impedance(Z_L, freq_MHz, self.p.Z0_ohm, self.length_m,
                                     self.p.v_f, self._alpha(freq_MHz))

    def tank(self, freq_MHz, chi_eff=0.0):
        """Series tank impedance Z_T (ohm) including the varactor setting."""
        C = self.C_F + self.dC_pF * 1e-12
        return tank_impedance(freq_MHz, self._z_in(freq_MHz, chi_eff), self.p.R_damp_ohm, C)

    def voltage(self, freq_MHz, chi_eff=0.0):
        """Complex detector-node voltage (V) on ``freq_MHz`` for susceptibility chi_eff."""
        return node_voltage(self.tank(freq_MHz, chi_eff), self.p.U_V,
                            self.p.R_cc_ohm, self.p.Z_amp_ohm)

    def ref_phase_rad(self):
        """Phase-detector reference phase, rad (absorptive + offset + phase DAC)."""
        return self.phi_abs + np.radians(self.p.ref_phase_offset_deg + self.dphi_deg)

    def detect(self, V):
        """(phase_V, diode_V) detector outputs for complex node voltage V."""
        phase = self.G_phase * np.real(V * np.exp(-1j * self.ref_phase_rad()))
        diode = self.G_diode * np.abs(V)
        return phase, diode

    def set_dac(self, value, channel):
        """Apply a Tune-tab DAC setting.

        Args:
            value: 0 (off) to 1 (max), as sent by PyNMR
            channel: 1 phase, 2 diode (varactor), 3 both, 0 no-op
        """
        if channel in (2, 3):
            self.dC_pF = self.p.varactor_span_pF * float(value)
        if channel in (1, 3):
            self.dphi_deg = self.p.phase_dac_span_deg * float(value)

    def loaded_Q(self):
        """Effective circuit Q = w0 L0 / Re Z_T(f0) (tuned, chi = 0), dimensionless."""
        return float(omega(self.f0) * self.L0_H / np.real(self.tank(self.f0, 0.0)))

    def summary(self):
        """Dict of derived circuit quantities for printing/logging."""
        return {
            "tune_MHz": self.f0,
            "C_tune_pF": self.C_F * 1e12,
            "cable_length_m": self.length_m,
            "loaded_Q": self.loaded_Q(),
            "Re_Z_T_at_tune_ohm": float(np.real(self.tank(self.f0))),
            "ref_phase_abs_deg": float(np.degrees(self.phi_abs)),
            "G_phase": self.G_phase,
            "G_diode": self.G_diode,
            "params": asdict(self.p),
        }
