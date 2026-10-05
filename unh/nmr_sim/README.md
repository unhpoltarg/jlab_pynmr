# nmr_sim: simulated deuteron NMR for PyNMR Test mode

`nmr_sim` produces realistic deuteron NMR sweeps without hardware. It is the
alternative to the replay Test source (`utils/d_signal_event.txt` plus noise).
The two sources compare like this:

| | Replay (`-p Test`) | nmr_sim (`-p TestSim`) |
|---|---|---|
| Signal | one recorded event, every chunk the same | physics model, depends on P(t) |
| Frequency axis | recorded at 31.83 MHz, drawn on the channel axis | computed on the channel's own axis |
| Baseline | impossible, since the signal is always there | the line moves off-window in a baseline segment |
| P(t) | constant | baseline, TE, spin-up (τ), T1 relaxation |
| Noise | uniform, nonzero mean, grows with N | Gaussian, zero mean, σ/√N |
| Tune-tab DACs | ignored | detune the circuit / rotate the reference phase |

## Using it

```powershell
conda run -n pynmr --no-capture-output python pynmr_main.py -p TestSim
```

You can also pick **TestSim** from the startup profile dialog.

- **The clock starts the first time PyNMR builds a DAQ connection.** That happens at startup if a saved session restores the Tune-tab DACs, and otherwise at the first Run or Tune. Time then runs at `speed` × wall time.
- **Default timeline** (at `speed: 60`):
  1. 2 min wall of **baseline**. The line sits 1.2 MHz above its nominal position, outside the window. Run a few events now, then in the Baseline tab click "Use last", select them, and set them as the baseline.
  2. 1 min of **TE** at P_TE ≈ 0.105 % (1 K, 5 T).
  3. **Spin-up** to P∞ = 40 % with τ = 1 min wall, lasting 6 min.
  4. **T1 relaxation** (3 min wall) back toward P_TE, continuing indefinitely.
- **Relaunching PyNMR restarts the timeline.** Use `start_at_s` to start partway through it.
- **Each chunk adds a row to `log/nmr_sim_truth_<UTC>.csv`.** The columns are wall time, sim time, segment, true P, Q, r, Larmor frequency, line offset, sweeps and DAC state. To compare an analysed event against the truth, average P over the event's `start_stamp`..`stop_stamp`.
- **To check a configuration without the GUI:**

  ```powershell
  conda run -n pynmr --no-capture-output python -m unh.nmr_sim --profile TestSim
  ```

  It prints the circuit, the background levels, the signal size against P, and the timeline.

## Physics pipeline

```
SimClock ─► Timeline ─► P, line offset ─► Susceptibility ─► chi_eff(f) ─► QMeter ─► V(f) ─► detect ─► + noise
 (wall×speed)  (segments)               (Dulya lineshape)  4πη(χ'−iχ'')  (Court 1993)          phase, diode
```

| Module | Contents |
|---|---|
| `lineshape.py` | Port of `optimized-mcclellan-fits/fitter/deuteron_model.py` at commit `0f4b4a8`: the Dulya spin-1 model, `FastModel`, `MATERIALS`. The header lists what was ported, added and omitted. |
| `susceptibility.py` | χ_eff = k·(D − iA), where A and D are the model's absorptive and dispersive curves. The sign of D follows from Kramers–Kronig (`DISPERSION_SIGN`, fixed by a test). |
| `qmeter.py` | Constant-current series Q-meter (Court et al., NIM A 324 (1993) 433). The coil is L₀(1+χ_eff) and sits behind a lossy λ/2 cable. Tuning capacitor, damping resistor, phase-sensitive and diode detectors. The capacitor auto-tunes; the detector gains are calibrated to the replay levels (phase −2.78 V, diode −0.526 V). |
| `timeline.py` | `hold`, `spinup` and `relax` segments; spin-1 P_TE. |
| `noise.py` | Gaussian noise σ/√N per chunk, plus optional drift (off by default). |
| `simulator.py` | Ties the modules together. Holds the process singleton (the clock and DAC state survive DAQ reconnects) and the truth log. |
| `adapter.py` | `SimDAQ`, which speaks PyNMR's `get_chunk`/`set_dac` contract. It is the only module PyNMR imports. |
| `params.py` | Defaults. Unknown keys raise an error, and the config dict is never mutated. |

**Amplitude.** `calibration: {P, peak_phase_V}` sets the coupling k. With it, a line centred on the tune frequency at polarization P has a phase-signal peak of `peak_phase_V`.

The default (8e-4 V at P = 0.19 %) assumes the replay event's `pol = 0.19` means 0.19 %. PyNMR P is a fraction, so if that event's CC were real it would mean 19 %, and the signal would be 100× smaller. That event's CC of −4 looks like a placeholder. **Set this from real UNH data when available.**

**Q-meter defaults are not measured UNH values.** L₀ = 0.25 µH, R_damp = 25 Ω and an open detector were chosen to reproduce the replay's nearly flat Q-curve: diode about 1–3 %, phase about 0.2 % across ±0.4 MHz. That shape requires a heavily damped circuit, with coil Q ≈ 2.

**Default material is ND₃** ("deuterated ammonia (Dec 2024)", single bond). PyNMR's FitDeuteron is a single-bond model, so sim-against-fit comparisons aren't confounded by a model mismatch. Set `material` to a d-butanol preset, or give a dict of constants, for double-bond lines.

## Configuration (`settings: nmr_sim:` in a profile)

Every key is optional; see `params.DEFAULTS`.

| Key | Meaning |
|---|---|
| `seed` | RNG seed. Use `null` for a new seed each launch; it is printed and logged. |
| `speed`, `start_at_s` | Clock: simulated seconds per wall second, and the starting sim time. |
| `sweep_time_s` | Wall-clock sleep per sweep in `get_chunk` (default 0.005 s, same as replay). |
| `field_T` | Magnet field. `null` puts the Larmor frequency on the tune frequency. γ_D/2π = 6.536 MHz/T. |
| `te_temp_K` | Lattice temperature for P_TE. |
| `material` | A `lineshape.MATERIALS` key, or a dict `{model, omegQ1, A1, eta1[, omegQ2, eta2, K]}` (MHz). |
| `calibration` | `{P, peak_phase_V}`, as described under Amplitude. |
| `qmeter` | Fields of `qmeter.QMeterParams`. Tune-tab DACs (0–1) map to `varactor_span_pF` and `phase_dac_span_deg`. |
| `noise` | `sigma_phase_V`, `sigma_diode_V` (per sweep), `drift_amp_V`, `drift_period_s`, `drift_rate_V_per_h`. |
| `truth_log_dir` | Where the truth CSV goes (`null` turns it off). |
| `timeline` | A list of segments: `{name, kind: hold, P: <num or te>, duration_s, line_offset_MHz}`, `{kind: spinup, P_inf, tau_s, ...}`, `{kind: relax, T1_s, P_eq (default te), ...}`. Durations are in sim seconds; only the last can be `null`. |

## Connection points into PyNMR (and how to remove nmr_sim)

nmr_sim imports nothing from `core/`, `gui/`, `hardware/`, `config/`, `utils/` or PySide6, and a test enforces this. PyNMR touches it only at the places below, each marked `UNH-HOOK nmr-sim` (see [unh/README.md](../README.md)). List them with `git grep -n "UNH-HOOK nmr-sim"`.

1. **`hardware/daq.py`**, three blocks in `DAQConnection`:
   - (1/3) an `elif` branch in `__init__` that builds `unh.nmr_sim.adapter.SimDAQ` when `settings['test_source'] == 'sim'`. The import is lazy, so replay never imports nmr_sim.
   - (2/3) an `elif` branch in `get_chunk` that delegates to the simulator.
   - (3/3) an `if` in `set_dac` that forwards the Tune-tab DACs.

   The replay code itself is unchanged.
2. **`pynmr_config.yaml`**: the `TestSim` profile.
3. **`.gitignore`**: two lines, `config/sim_session.yaml` and `config/sim_history.json`.

To remove nmr_sim: `python -m unh.strip_unh --feature nmr-sim --apply` deletes `unh/nmr_sim/` and those blocks.

## Tests

```powershell
conda run -n pynmr --no-capture-output python -m pytest unh/nmr_sim/tests -p no:cacheprovider -q
```

Run this from the repo root. The tests never import `utils/`, so PyNMR's broken pytest collection doesn't affect them. They cover:
- the port matches the source `FastModel` to 1e-12 (skipped if `../optimized-mcclellan-fits` is missing; set `MCCLELLAN_FITS_DIR` to point elsewhere)
- the Kramers–Kronig sign
- `r_of_P` round-trip, and P_TE equal to `ratio_P(e^x)`
- λ/2 and λ/4 cable limits, auto-tune, and the ideal-circuit FWHM of f₀/Q
- small-χ linearity: absorption at the matched phase, dispersion at +90°
- DAC detune and restore
- timeline limits and continuity
- noise σ/√N and zero mean
- the baseline segment has no in-window signal
- the calibrated peak height
- the clock, the singleton, and the DAQ tuple contract
- config validation and no mutation of the input
- the isolation rule above

## Limits and TODO

- **TODO: hole burning.** It needs the branch-swapped (`*_rev`) and `bump` functions from the source model, which were deliberately left out of the port. The source's `generate_test_cooldown.py` (the `Physics` class) has the burn and heal logic to follow.
- **Single spin temperature.** Q is derived from P through r; there are no frequency-hopping or two-temperature lines yet. The source has an experimental `nonbolt` model.
- **Noise isn't bit-reproducible in the GUI.** Chunk requests from the GUI, Run and Tune threads interleave nondeterministically. It is reproducible headless.
- **NumPy only, no CuPy.** Each chunk is 512 points, and CuPy isn't installed in the `pynmr` environment.
- **The Q-meter tune frequency is fixed** at the centre of the first sweep window, the way a real circuit doesn't retune when the window moves.
