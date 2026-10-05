"""Print the configured simulation: Q-meter summary, calibration and timeline.

    python -m nmr_sim [--config pynmr_config.yaml] [--profile TestSim]

Reads the YAML directly (no PyNMR imports). The sweep axis is rebuilt from the
profile's default channel with the standard 512-step profile.
"""

import argparse

import numpy as np
import yaml

from .simulator import Simulator


def _profile_settings(config_file, profile):
    with open(config_file) as f:
        data = yaml.safe_load(f)
    prof = data.get("profiles", {}).get(profile)
    if prof is None:
        raise SystemExit(f"Profile {profile!r} not found in {config_file}")
    settings = dict(data.get("settings", {}))
    settings.update(prof.get("settings", {}))
    channels = prof.get("channels", data.get("channels", {}))
    channel = channels[settings["default_channel"]]
    return settings, channel


def main():
    ap = argparse.ArgumentParser(prog="python -m nmr_sim", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="pynmr_config.yaml")
    ap.add_argument("--profile", default="TestSim")
    args = ap.parse_args()

    settings, channel = _profile_settings(args.config, args.profile)
    sim_cfg = dict(settings.get("nmr_sim", {}), truth_log_dir=None)
    steps = settings.get("steps", 512)
    ints = np.linspace(-32768, 32767, num=steps).astype("int32")
    freq = channel["cent_freq"] + channel["mod_freq"] / 1000 * ints / 32768

    sim = Simulator(sim_cfg, 0.5 * (freq.min() + freq.max()))
    s = sim.summary()
    q = s.pop("qmeter")
    print(f"nmr_sim {args.profile}: channel {channel['name']}, "
          f"{freq.min():.4f}-{freq.max():.4f} MHz, {steps} points")
    print(f"  seed {s['seed']}, field {s['field_T']:.6f} T, Larmor {s['larmor_MHz']:.5f} MHz, "
          f"P_TE {s['P_te']:.6f} at {sim.cfg['te_temp_K']} K")
    print(f"  material: {sim.cfg['material']}")
    print(f"  Q-meter: tune {q['tune_MHz']:.5f} MHz, C {q['C_tune_pF']:.2f} pF, "
          f"cable {q['cable_length_m']:.3f} m, coil Q {q['loaded_Q']:.2f}, "
          f"Re Z_T {q['Re_Z_T_at_tune_ohm']:.2f} ohm")
    ph0, di0 = sim.qmeter.detect(sim.qmeter.voltage(freq, 0.0))
    print(f"  background: phase {ph0[0]:.4f} / {ph0[len(freq)//2]:.4f} / {ph0[-1]:.4f} V, "
          f"diode {di0[0]:.4f} / {di0[len(freq)//2]:.4f} / {di0[-1]:.4f} V (low/mid/high)")
    print(f"  coupling k {s['coupling_k_MHz']:.4e} MHz -> peak |4 pi eta chi| at P~1: "
          f"{s['peak_chi_eff_abs_at_P~1']:.4f}")
    for P in sorted({sim.cfg["calibration"]["P"], sim.P_te, 0.1, 0.25, 0.4}):
        chi = sim.chi.chi_eff(freq, sim.larmor0_MHz, P)
        ph, _ = sim.qmeter.detect(sim.qmeter.voltage(freq, chi))
        sig = ph - ph0
        lin = sig.min() / P
        print(f"    P={P:8.5f}: phase signal peak {sig.min():+.4e} V  (peak/P {lin:+.4e} V)")
    n = sim.noise
    print(f"  noise: {n.sigma_phase_V:.2e} V/sweep phase, {n.sigma_diode_V:.2e} V/sweep diode; "
          f"speed {sim.cfg['speed']}x")
    print("  timeline (simulated s; wall s = sim / speed):")
    for name, kind, start, dur, off, P0, P1 in sim.timeline.table():
        d = "forever" if dur is None else f"{dur:.0f}"
        print(f"    {name:10s} {kind:7s} start {start:8.0f}  dur {d:>8s}  "
              f"offset {off:+.2f} MHz  P {P0:.5f} -> {P1:.5f}")


if __name__ == "__main__":
    main()
