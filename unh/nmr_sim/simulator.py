"""Deuteron NMR signal simulator: timeline -> susceptibility -> Q-meter -> detector.

``get_simulator`` keeps one Simulator per process so the simulated clock,
noise generator and Tune-tab DAC state persist while PyNMR creates and
destroys DAQ connections (GUI, run and tune threads all do this).
"""

import csv
import datetime
import json
import os
import threading
import warnings

import numpy as np

from .clock import SimClock
from .lineshape import r_of_P, ratio_Q
from .noise import NoiseModel
from .params import resolve
from .qmeter import QMeter, QMeterParams
from .susceptibility import Susceptibility
from .timeline import Timeline, p_te

GAMMA_D_MHZ_PER_T = 6.536   # deuteron gyromagnetic ratio / 2 pi, MHz/T

# Calibration grid: +-0.5 MHz about the tune frequency.
_CAL_HALF_WIDTH_MHZ = 0.5
_CAL_POINTS = 1001

TRUTH_COLUMNS = ["unix_time", "t_sim_s", "segment", "P", "Q", "r", "larmor_MHz",
                 "line_offset_MHz", "n_sweeps", "dC_pF", "phase_dac_deg"]


class Simulator:
    """Deuteron NMR simulator.

    Args:
        cfg: nmr_sim config dict (see params.DEFAULTS); not mutated
        tune_MHz: Q-meter tune frequency, MHz (if qmeter.tune_MHz is None)
        clock: SimClock (default: built from cfg speed/start_at_s)
    """

    def __init__(self, cfg, tune_MHz, clock=None):
        self.cfg = resolve(cfg)
        c = self.cfg
        if c["seed"] is None:
            self.seed = int(np.random.SeedSequence().entropy)
        else:
            self.seed = int(c["seed"])
        self.rng = np.random.default_rng(self.seed)
        self.qmeter = QMeter(QMeterParams(**c["qmeter"]), tune_MHz)
        self.field_T = (c["field_T"] if c["field_T"] is not None
                        else self.qmeter.f0 / GAMMA_D_MHZ_PER_T)
        self.larmor0_MHz = GAMMA_D_MHZ_PER_T * self.field_T
        self.chi = Susceptibility(c["material"], 1.0)
        self.chi.coupling = self._calibrate_coupling()
        self.P_te = p_te(self.larmor0_MHz, c["te_temp_K"])
        self.timeline = Timeline(c["timeline"], self.P_te)
        self.noise = NoiseModel(self.rng, **c["noise"])
        self.clock = clock if clock is not None else SimClock(c["speed"], c["start_at_s"])
        self.lock = threading.Lock()
        self._truth_writer = None
        self._truth_file = None
        self.truth_path = None

    # -- calibration -------------------------------------------------------
    def _calibrate_coupling(self):
        """Coupling k such that the phase-signal peak at calibration.P, with the
        line centred on the tune frequency, has height calibration.peak_phase_V.

        Uses a tiny trial coupling (max |chi_eff| = 1e-7) where the Q-meter
        response is linear, then scales.
        """
        cal = self.cfg["calibration"]
        f0 = self.qmeter.f0
        grid = np.linspace(f0 - _CAL_HALF_WIDTH_MHZ, f0 + _CAL_HALF_WIDTH_MHZ, _CAL_POINTS)
        A, D = self.chi.parts(grid, f0, cal["P"])
        peak = max(np.max(np.abs(A)), np.max(np.abs(D)))
        if peak == 0:
            raise ValueError("calibration.P must be nonzero")
        k_trial = 1e-7 / peak
        chi = self.chi.chi_eff(grid, f0, cal["P"], coupling=k_trial)
        ph1, _ = self.qmeter.detect(self.qmeter.voltage(grid, chi))
        ph0, _ = self.qmeter.detect(self.qmeter.voltage(grid, 0.0))
        resp = np.max(np.abs(ph1 - ph0))
        return k_trial * abs(cal["peak_phase_V"]) / resp

    # -- signal ------------------------------------------------------------
    def noiseless(self, freq_MHz, t_s):
        """Noise-free (phase_V, diode_V, truth) on ``freq_MHz`` at simulated time t_s.

        Includes the configured drift (deterministic); excludes white noise.
        """
        freq_MHz = np.asarray(freq_MHz, dtype=float)
        st = self.timeline.state(t_s)
        larmor = self.larmor0_MHz + st.line_offset_MHz
        chi = self.chi.chi_eff(freq_MHz, larmor, st.P)
        phase, diode = self.qmeter.detect(self.qmeter.voltage(freq_MHz, chi))
        phase = phase + self.noise.drift_V(t_s)
        r = r_of_P(st.P)
        truth = {
            "t_sim_s": float(t_s), "segment": st.name, "P": st.P, "Q": float(ratio_Q(r)),
            "r": r, "larmor_MHz": larmor, "line_offset_MHz": st.line_offset_MHz,
            "dC_pF": self.qmeter.dC_pF, "phase_dac_deg": self.qmeter.dphi_deg,
        }
        return phase, diode, truth

    def sweep(self, freq_MHz, n_sweeps):
        """One chunk: the average of n_sweeps sweeps, at the current simulated time.

        Returns (phase_V, diode_V, truth); also appends a truth-log row.
        """
        with self.lock:
            t = self.clock.now_s()
            phase, diode, truth = self.noiseless(freq_MHz, t)
            dp, dd = self.noise.sample(len(phase), n_sweeps)
            truth["n_sweeps"] = int(n_sweeps)
            truth["unix_time"] = datetime.datetime.now().timestamp()
            self._log_truth(truth)
        return phase + dp, diode + dd, truth

    def set_dac(self, value, channel):
        """Forward a Tune-tab DAC setting to the Q-meter (thread-safe)."""
        with self.lock:
            self.qmeter.set_dac(value, channel)

    # -- truth log ---------------------------------------------------------
    def _log_truth(self, truth):
        log_dir = self.cfg["truth_log_dir"]
        if log_dir is None:
            return
        if self._truth_writer is None:
            os.makedirs(log_dir, exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self.truth_path = os.path.join(log_dir, f"nmr_sim_truth_{stamp}.csv")
            self._truth_file = open(self.truth_path, "w", newline="")
            self._truth_file.write(f"# nmr_sim truth log, seed={self.seed}, "
                                   f"started_unix={self.clock.started_unix:.3f}\n")
            self._truth_file.write("# config=" + json.dumps(self.cfg) + "\n")
            self._truth_writer = csv.DictWriter(self._truth_file, fieldnames=TRUTH_COLUMNS,
                                                extrasaction="ignore")
            self._truth_writer.writeheader()
            print(f"nmr_sim: truth log -> {self.truth_path}")
        self._truth_writer.writerow(truth)
        self._truth_file.flush()

    def summary(self):
        """Dict describing the configured simulation (for printing)."""
        f0 = self.qmeter.f0
        grid = np.linspace(f0 - _CAL_HALF_WIDTH_MHZ, f0 + _CAL_HALF_WIDTH_MHZ, _CAL_POINTS)
        A, _ = self.chi.parts(grid, f0, 0.999)
        return {
            "seed": self.seed,
            "field_T": self.field_T,
            "larmor_MHz": self.larmor0_MHz,
            "P_te": self.P_te,
            "coupling_k_MHz": self.chi.coupling,
            "peak_chi_eff_abs_at_P~1": float(self.chi.coupling * np.max(np.abs(A))),
            "qmeter": self.qmeter.summary(),
        }


_SIM = None
_SIM_LOCK = threading.Lock()


def get_simulator(cfg, freq_MHz):
    """Process-wide Simulator, created on first call.

    Args:
        cfg: nmr_sim config dict
        freq_MHz: sweep frequency grid, MHz; its centre sets the tune frequency
            the first time only (a real Q-meter is not retuned when the sweep
            window changes)
    """
    global _SIM
    with _SIM_LOCK:
        if _SIM is None:
            f = np.asarray(freq_MHz, dtype=float)
            _SIM = Simulator(cfg, 0.5 * (f.min() + f.max()))
            print(f"nmr_sim: simulator started, seed={_SIM.seed}, "
                  f"tune={_SIM.qmeter.f0:.4f} MHz, Q={_SIM.qmeter.loaded_Q():.1f}")
        elif resolve(cfg) != _SIM.cfg:
            warnings.warn("nmr_sim: config changed after the simulator started; "
                          "keeping the running simulator (restart PyNMR to apply).")
        return _SIM


def reset_simulator():
    """Drop the process-wide Simulator (for tests)."""
    global _SIM
    with _SIM_LOCK:
        if _SIM is not None and _SIM._truth_file is not None:
            _SIM._truth_file.close()
        _SIM = None
