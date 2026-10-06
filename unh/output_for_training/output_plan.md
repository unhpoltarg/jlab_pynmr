# Output plan: PyNMR event data for ML training

Status: planning only. Nothing here is implemented yet.

## Purpose

From now on, PyNMR event files should hold everything needed to train ML models of the NMR signal. Any value we
can't record online must be recoverable in offline analysis.
The models are wanted for two jobs, eventually both:

- **Forward (signal emulator):** conditions in, realistic sweep out. Used to tune and extend simulation (`unh/nmr_sim`).
- **Inverse (analysis):** sweep in, physics out (polarization, lineshape and fit parameters, circuit state).

Scope: PyNMR event files going forward. Old LabVIEW data is out of scope.

The plan starts from two areas recommended to us: **A. static signal fitting** and **B. dynamic signal
characterization**. Each item is listed first, followed by what we think we need to deliver it. **C** lists
needs that run across both areas. **D** lists what the offline analysis pipeline (Optimized-McClellan-Fits) needs
from each event.

## How each need is tagged

- `[online]`: written to the event file at run time.
- `[offline]`: not written at run time, but can be computed later because the inputs are saved.
- `[external]`: comes from another system (EPICS/archiver, logbook) and is joined by timestamp. Prefer copying it
  into the event file when PyNMR can read it.
- `[operator]`: entered by hand (material, cell, run type).
- `[ssRF]`: needs ssRF, which isn't built yet. Planned now so the format has room for it; revisit when ssRF lands.

**Now:** lines say what PyNMR records today, from a read-only survey of `unh` at 7d9fa52 (2026-10-06).
A summary of today's event file is in [Current state in PyNMR](#current-state-in-pynmr).

## Summary

The tags are the source tags used for that item's needs (see above). The status tags are:
- `[done]`: PyNMR already records everything the item needs.
- `[to-do]`: something is still missing. That includes items that are partly covered; the item's **Now:** line says what.

| Item | Needs | Tags | Status&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; |
|---|---|---|---|
| **A1** | Number of frequency bins: axis, sampling, window changes | `[online]` | `[to-do]` |
| **A2** | RF background: baseline used, raw signal, RF settings, diode | `[online]` `[operator]` | `[to-do]` |
| **A3** | Baseline drift: baseline age, tune state, electronics temperature | `[online]` `[external]` `[offline]` | `[to-do]` |
| **A4** | NMR circuit characterization: circuit parameters, calibration | `[operator]` `[offline]` `[online]` | `[to-do]` |
| **A5** | Material specifics: material ID, lineshape fit results, artifacts | `[operator]` `[online]` `[offline]` | `[to-do]` |
| **A6** | Noise at the maximum number of sweeps: actual sweeps, per-point noise | `[online]` `[offline]` | `[to-do]` |
| **A7** | Latency budget: chunk, analysis and RF timestamps; sweep rate | `[online]` `[offline]` | `[to-do]` |
| **A8** | Precision against speed: sweeps per event, RF cadence | `[online]` `[offline]` | `[to-do]` |
| **B1** | Spin diffusion against field, temperature and microwaves | `[external]` `[online]` `[operator]` | `[to-do]` |
| **B2** | Cooldown data: run type, continuous logging, TE provenance | `[online]` `[operator]` `[offline]` `[external]` | `[to-do]` |
| **B3** | Coil characterization and ssRF power calibration | `[ssRF]` `[offline]` | `[to-do]` |
| **B4** | Hole burning across the spectrum | `[ssRF]` `[offline]` | `[to-do]` |
| **B5** | Full saturation and recovery, with and without microwaves | `[ssRF]` `[online]` `[external]` | `[to-do]` |
| **C1** | Identity and provenance: IDs, profile, git commit, config | `[online]` | `[to-do]` |
| **C2** | Raw and processed both saved | `[online]` | `[done]` |
| **C3** | Analysis method and parameters recorded | `[online]` | `[to-do]` |
| **C4** | Units and schema version | `[online]` | `[to-do]` |
| **C5** | Labels with known truth: TE events, simulation truth | `[online]` | `[to-do]` |
| **C6** | Data policy: real data stays out of git | (policy) | `[done]` |
| **C7** | Run outcome and data quality flags | `[online]` | `[to-do]` |

Section D (what the offline pipeline needs) maps onto these items, mostly A3, B1, B2 and the ssRF items.

---

## A. Static signal fitting

The tutorial already covers the general method. Each NMR/RF setup still has specifics that the training data must capture.

- **A1. Number of frequency bins**
  - `[online]` Number of points, the frequency of every point (or centre, half-width and step, if the axis is
    exactly uniform), and the sweep direction.
  - `[online]` DAQ sampling settings that set the bins (samples per sweep, sweep time, any decimation or averaging).
  - `[online]` A per-event record whenever the window changes mid-run (the Run tab window can now change between events).
  - **Now:** mostly covered.
    - `freq_list`, `steps`, `channel.cent_freq` and `mod_freq`, and all FPGA/NI DAQ settings (dwell, samples per
      point, ADC rates) are written to every event.
    - The FPGA sums the up and down ramps, so sweep direction isn't separable.
- **A2. RF background**
  - `[online]` The baseline actually subtracted for each event: the array itself, or an ID that points to a saved
    copy. Also when and how it was taken (field off, field shifted, off-resonance).
  - `[online]` Raw, unsubtracted signal for every event, so a different background model can be tried offline.
  - `[online]` RF source settings (R&S frequency, power level, modulation) and RF switch state.
  - `[online]` The diode channel. It is a direct measure of the RF level and is stored today but not used.
  - `[operator]` A run type for dedicated background runs (field off, empty cell), so they can be found later.
  - **Now:** partly covered.
    - Recorded: `baseline`, `basesweep` (what was subtracted), the raw `phase` and `diode`, and the R&S settings as configured.
    - The baseline's time and file are recorded. Which events were averaged into it, and its sweep count and
      window, are not; the event list is only in `recent_baselines.txt`.
    - Nothing checks that the baseline's window matches the event's.
    - R&S readbacks are read and thrown away.
    - RF switch state isn't recorded.
    - There is no run type. `label` is free text, read when the event closes.
- **A3. Drifts in baseline**
  - `[online]` A timestamp for the baseline, so its age at each event is known.
  - `[online]` Tune state per event: phase setting, tune voltage/capacitance, and gain.
  - `[external]` Q-meter electronics and cable temperatures, and room temperature where available. Drift usually tracks these.
  - `[offline]` The wing-only residual baseline fit (polynomial order, wing ranges, coefficients). Recoverable if
    the raw signal and baseline are saved and the method is recorded (C3).
  - **Now:** partly covered.
    - Recorded: `base_stamp`, `phase_vout` and `diode_vout` (tune DACs), and `chassis_temp` (value at event start).
    - Not recorded: Q-meter gain, IF attenuation, IF offset and board temperature. There is no software access to them.
    - The event's `wings` field is a fixed default, not the wings actually used.
    - Polynomial orders and coefficients are shown on screen only.
- **A4. Specific NMR circuit characterizations**
  - `[operator]` Circuit description: coil inductance and geometry, cable length (half-wavelength setting),
    tuning capacitor, damping resistor, amplifier gain, and Q-meter model and serial. These are the parameters the
    Court Q-meter model in `unh/nmr_sim` needs.
  - `[offline]` A circuit calibration measurement (e.g. a Q-curve with no NMR signal) stored with an ID, and a link from
    each event to the circuit calibration that applies.
  - `[online]` The tune state per event (shared with A3).
  - **Now:** not covered, apart from the tune DACs.
    - `CircuitBase` exists but is disabled.
    - The only place PyNMR keeps circuit parameters is the TestSim truth log.
- **A5. Material specifics: multisite, artifacts, Voigt deformations**
  - `[operator]` Material (ND3, d-butanol, ...), species/nucleus, batch, irradiation (dose, date),
    target cell/loading ID, and packing fraction if known.
  - `[online]`/`[offline]` Lineshape fit results: which model and version, every fitted parameter with its
    uncertainty (Dulya: r, eta, widths, centre, asymmetry), Voigt Gaussian and Lorentzian widths, multisite
    component fractions, residuals, and goodness of fit.
    - Online when the fit runs live; otherwise offline from the saved signal.
  - `[operator]` Known artifacts flagged by event or by run, so they can be labelled rather than learned as signal.
  - **Now:** mostly missing.
    - Only `channel.species` is recorded; nothing about the material.
    - Recorded: `fitsub` and `rescurve`, so fits can be redone offline.
    - The FitDeuteron parameters, uncertainties, χ² and success flag are shown on screen only.
    - In FitDeuteron mode `area` silently holds r.
    - EPICS `Target_Dose` is read when EPICS is on.
- **A6. Noise scale at the maximum number of sweeps**
  - The maximum number of sweeps per event is set by how fast the spin system evolves and by the latency in A7.
  - `[online]` Number of sweeps actually averaged into each event (not just the number requested).
  - `[online]` A per-point noise estimate, e.g. the running sum of squares alongside the running mean. This makes noise
    against number of sweeps recoverable without saving every sweep.
  - `[online]` Optionally, raw per-chunk or per-sweep data for a sample of events, to check that noise really
    scales as 1/√N.
  - `[offline]` Noise from the off-resonance wings.
  - **Now:** partly covered.
    - Recorded: `num` (actual sweeps) and `sweeps` (requested).
    - Per-chunk arrays are averaged and then discarded.
    - There's no per-point variance.
- **A7. Latency budget**
  - Acquisition, processing, inference and RF application must all finish before the signal changes.
    For example, 1 s is fast compared with d-butanol's evolution, but every one of those steps still has to fit inside it.
  - `[online]` Timestamps: event start and end, each chunk, analysis start and end, and (later) inference start and
    end and RF action applied.
  - `[online]` Sweep rate (time per sweep) and dead time between sweeps and between events.
  - `[offline]` How fast the signal is changing (dP/dt from the polarization time series), to compare with the latency.
  - **Now:** minimal.
    - Recorded: `start_stamp` and `stop_stamp`. The start is taken before the DAQ connects, so it includes setup time.
    - `elapsed` is truncated to whole seconds.
    - No chunk or analysis timing is recorded.
    - Sweep time can be estimated from `dwell`, `per_point` and `steps`.
- **A8. Statistical precision against speed**
  - We can trade some statistical precision for speed, or take more sweeps before each RF adjustment.
  - `[online]` The settings chosen (sweeps per event, RF adjustment cadence), recorded per event.
  - `[offline]` With A6 and A7 recorded, the trade-off can be modelled afterwards instead of fixed in advance.
  - **Now:** sweeps per event is recorded. There are no RF adjustments yet.

## B. Dynamic signal characterization

Simulations must be tuned to a particular material's spin diffusion rates, for a given field, temperature and microwave power.

- **B1. Spin diffusion rates against field, temperature and microwave power**
  - `[external]`, copied in where possible:
    - magnetic field (magnet current or field probe, and the NMR-derived value);
    - target temperature (each thermometer, with sensor ID);
    - microwave frequency and power (and where along the chain the power is measured);
    - microwave on/off state.
  - `[online]` Event timestamps precise enough to line up with these (UTC, with sub-second resolution).
  - `[operator]` Material (A5).
  - **Source (decided 2026-10-06):** UNH will run pyepics, which PyNMR's `hardware/epics.py` already uses.
    - The UNH slow-controls system is a separate project with its own owner.
    - Once its repo exists, link it here and map its PVs to these needs.
  - **Now:** weak.
    - EPICS is off in every profile. When on, it takes one snapshot of the read PVs **after** each event's analysis.
      There is no start value or average.
    - With EPICS off, every PV reads 0, not "missing".
    - Field is recorded only as the EPICS solenoid current. The magnet tab exists but isn't used, and the TE B field
      is in the TE file only.
    - Microwave frequency and power are the last reading only.
    - Microwave on/off, tuning moves and FM settings are not recorded.
    - Timestamps are UTC with sub-second resolution, which is good.
- **B2. Cooldown data on the exact material, under the exact conditions**
  - Run type is set in two stages (decided 2026-10-06):
    - `[online]`/`[operator]` A coarse status on every event, like LabVIEW's NMR Status
      (Baseline / Polarization / TE / Tuning / Scanning), plus a cooldown or run ID.
    - `[offline]` The full classification, done afterwards the way Optimized-McClellan-Fits does it for LabVIEW data:
      - signal-driven triage (equilibrium, hole-burnt, frequency-hopping, no signal);
      - spin-up and relaxation segments;
      - logbook windows for manipulations.
    - See section D for what the offline side needs from PyNMR.
  - `[online]` Continuous event logging through the whole cooldown, not only during data taking.
  - `[online]` TE calibration inputs and results: TE temperature, field, area, CC, and which events were used.
  - `[external]` Microwave on/off transitions with timestamps, which mark polarization build-up and decay curves.
  - **Now:** partly covered.
    - Every event's `cc` is recorded, but not which TE produced it.
    - The TE file has areas, temperatures, field and CC, but no event timestamps or labels.
    - The TE file goes to a hard-coded `te/` folder (known bug; fixed on `unh_dev/te_fix`).
    - TE events are found only by a label of "TE" or "None".
- **B3. Coil characterization and power calibration**
  - Apply just enough power to semi-saturate one frequency, and show the effect scales with power.
  - `[ssRF]` ssRF settings per event: frequency, power at the source and the attenuation chain (power at the coil),
    duration, and start and stop times relative to the sweeps.
  - `[ssRF]` A calibration-series ID that groups a power scan, with the hole depth at each power `[offline]`.
  - `[offline]` Coil and circuit characterization (A4).
  - **Now:** not covered (needs ssRF).
- **B4. Hole burning across the spectrum**
  - Burn all the way down at each frequency in the spectrum, at steps of the narrowest Voigt width we can achieve.
  - `[offline]` The narrowest achievable Voigt width, from A5 fits. This sets the burn frequency step.
  - `[ssRF]` The burn frequency grid, and a per-burn record of frequency, power, duration and series ID.
  - `[offline]` A check that each burn fully saturated (hole depth at the burn frequency).
  - **Now:** not covered (needs ssRF).
- **B5. Full saturation, then full recovery, with and without microwaves**
  - `[ssRF]` The saturation step itself (B3/B4 settings).
  - `[online]` Fast, closely spaced events through the whole recovery, using the A7 latency limits to pick the sweep count.
  - `[external]` Microwave state during recovery, and temperature (microwave heating changes the recovery).
  - Microwave build-up and decay without ssRF can be recorded now (B2). Only the burn needs ssRF.
  - **Now:** the saturation step isn't covered (needs ssRF). For recovery, see B1 for microwave state and A7 for timing.

## C. Needs across both areas

- **C1. Identity and provenance**
  - `[online]` Event ID, run ID, profile, channel.
  - `[online]` PyNMR git commit, plus any uncommitted changes.
  - `[online]` A full config snapshot (or hash plus saved copy) for each run, so every setting at the time is known.
  - **Now:**
    - The merged `settings` and `channel` are written with every event.
    - Profile name, config path, git commit and hostname are not.
    - There is no event or run ID. Events are identified by `stop_stamp`.
    - `settings` is dumped when the event is written. The Compare tab can change `daq_type` mid-run, so the recorded
      value may not be the one used.
- **C2. Raw and processed both saved**
  - `[online]` Averaged raw phase and diode, frequency axis, baseline (or its ID), fitsub, and the results.
  - Offline re-analysis needs the raw signal; ML labels need the results.
  - **Now:** covered at the event-average level. All intermediate arrays are written.
- **C3. Analysis method recorded, not just its result**
  - `[online]` Baseline, sub and res modules used, with their parameters (`gui/tabs/analysis_modules.py`) and versions.
  - **Now:** not covered.
    - Only the analysis defaults from the config are written. They aren't necessarily what was selected.
    - The wings, polynomial orders, sum range and Dulya starting values actually used are missing.
    - A re-analysis on the Analysis tab updates EPICS but not the event file or history.
- **C4. Units and schema**
  - Every stored field gets a unit.
  - The event format gets a schema version, so later readers know what each file holds.
  - **Now:**
    - There's no schema version or units.
    - Units differ between fields (MHz, kHz and mV in `channel`; uwave power labelled mW in the GUI and W in the config).
    - NaN is written bare, which is not valid JSON.
    - The Explore tab still reads the old `epics_reads` key.
- **C5. Labels with known truth**
  - Real data has no ground-truth polarization except at TE. Mark TE events clearly.
  - Simulated events (`unh/nmr_sim`) should use the same format, plus the true parameters that generated them.
  - **Now:**
    - TestSim writes truth per chunk to `log/nmr_sim_truth_*.csv`. It can be joined to events only by timestamp.
    - The resolved seed and simulator summary are not in the event.
    - `unh_dev/output_checker` (not merged) already has a reader for event files and a truth join that we can reuse.
- **C6. Data policy**
  - Real UNH data, and anything derived from it, stays out of git until published.
  - The plan, schema and code can be committed; the data and trained models can't.
- **C7. Run outcome and data quality** (added after the survey)
  - `[online]` A status for each event: completed, aborted, chunk lost, or analysis failed.
  - **Now:**
    - An analysis that raises still writes a partly analysed event, with `analysis_completed` = True.
    - The only hint of an aborted or short event is `num` < `sweeps`.

## D. Compatibility with the offline pipeline (Optimized-McClellan-Fits)

Run-type classification and the full offline fits will follow `../optimized-mcclellan-fits`. That pipeline was built
for LabVIEW cooldown files, and it relies on metadata columns that LabVIEW wrote with every sweep. PyNMR events
need an equivalent for each of them, or that pipeline can't run on PyNMR data.

Each row gives the column the pipeline reads (from `fitter/cooldown_io.py`), what the pipeline uses it for, and PyNMR today.

- **Timestamp:** Used for everything.
  - **PyNMR now:** `start_stamp` and `stop_stamp` (UTC).
- **Central Mag Field (T), Magnet Current (A):** Field; a NaN means the magnet is off.
  - **PyNMR now:** missing (B1).
- **Holeburning Frequency (MHz), Holeburning Power (dBm):** ssRF settings for each sweep.
  - **PyNMR now:** missing `[ssRF]` (B3, B4).
- **NMR Central Freq, NMR Freq Span:** The window. Also part of the "instrument epoch".
  - **PyNMR now:** `channel.cent_freq` and `mod_freq`.
- **Phase Tune (V):** Part of the epoch (tune signature).
  - **PyNMR now:** `phase_vout` (DAC fraction, not volts).
- **IF Attenuation (dB):** Part of the epoch.
  - **PyNMR now:** missing, with no software access (A3).
- **VME Mode (amplifier mode):** Amplitude scaling between modes (a fixed, measured gain ratio between Operating and Phase). Part of the epoch.
  - **PyNMR now:** missing (A3).
- **NMR Domain (Real/Imaginary):** Which signal is recorded. LabVIEW also had a span quirk here.
  - **PyNMR now:** implicitly phase (real) only; not recorded.
- **NMR Status:** Coarse online run type, used as a prior by the triage.
  - **PyNMR now:** missing. Only a free-text `label` (B2).
- **Area/Polarization:** The live online result, for comparison.
  - **PyNMR now:** `area` and `pol`.
- **NMR Number (and the sweep):** Number of points, and the sweep itself.
  - **PyNMR now:** `freq_list` and `phase`.

Other lessons from that pipeline:
- **CC is set per instrument epoch.** An epoch is a stretch with the same amplifier mode, phase tune, IF attenuation,
  centre and span. So all five must be recorded on every event, or the epochs can't be found.
- **The operator logbook is the ground truth for manipulations** (ssRF and AFP windows).
  - It's free text, its clock is a few minutes off from the DAQ, and it has to be matched by keyword.
  - PyNMR should timestamp manipulations itself when it drives them, using the same clock as the events.
- **AFP (adiabatic fast passage)** is a second manipulation, besides ssRF, to plan for in the format.
- **The offline fits report** both the area method and a routed fit (single-r for equilibrium, the hole-burnt fit for
  ssRF), plus the component curves.
  - Online PyNMR results should be stored in a form that's easy to compare with these.

## Current state in PyNMR

A summary of the survey. The per-item **Now:** lines above have the details.

- **Event file:**
  - JSON lines, one object per event, in `<event_dir>/<start>__<close>.txt`.
  - A new file starts at each app launch and after every 501 events.
  - Each event dumps the scan, the event attributes and the flattened config, so new attributes are written automatically.
- **Well covered:**
  - averaged raw `phase` and `diode`;
  - the frequency axis;
  - every intermediate analysis array;
  - area, pol and cc;
  - sweeps actually averaged;
  - full DAQ and RF settings;
  - tune DACs;
  - UTC timestamps.
- **Biggest gaps for training:**
  - **Material and circuit:** none of either recorded (A4, A5).
  - **Analysis:** the method actually used and its fit parameters (C3, A5).
  - **Environment:** field, temperature and microwave state. EPICS is off by default, and when on, it is read once after the event (B1).
  - **Noise and timing:** below the event average (A6, A7).
  - **Provenance:** baseline and CC (A2, B2).
  - **Run identity:** run, version and outcome (C1, C7).
- **Other files:**
  - **History** (`config/*history.json`): a short summary per event, without the window, channel or sweep count.
  - **Session file:** tune, cc, channel and the window, saved on close.
  - **`recent_baselines.txt`:** baseline averages with their source events.
  - **TE file:** the TE results.
  - **Screenshots:** a PNG of the Run tab after each event.

## Open questions

1. **Hardware readback.**
   - Can the UNH Q-meter's gain, IF attenuation and offset, and board temperature be read at all? Today PyNMR has no
     access to them (A3).
   - Amplifier mode and IF attenuation also define the offline CC epochs (D), so they matter twice.
   - Which instruments does UNH actually run, so we know which inputs to plan for?
     - DAQ: FPGA or NI.
     - Field: magnet supply or field probe.
     - Thermometry.
     - Microwaves: source, counter and power meter.
2. **Environment source.** *Partly answered 2026-10-06.*
   - UNH will run pyepics. A separate project, with its own owner, will provide the PVs. Its repo link is to come.
   - Still open: should values be recorded at event start and end, or averaged over the event, rather than one snapshot afterwards?
3. **Operator metadata.** *Partly answered 2026-10-06.*
   - Decided: operators enter the material. Run type is a coarse online status plus the full offline classification (B2, D).
   - Still open: what we need for the cell and the circuit, and where it's entered.
   - **Cell:** identifies the physical sample, so batch and loading effects can be separated in training.
     - Proposed minimum per event: a cell or loading ID.
     - Proposed per cooldown, in a sheet keyed by that ID: material batch, irradiation (dose, date), loading date and
       packing fraction if known.
   - **Circuit:** the Q-meter and coil parameters that shape the background and the signal.
     - Proposed minimum per event: the tune signature from D (amplifier mode, IF attenuation, phase tune).
     - Proposed per cooldown, in a circuit sheet keyed by ID: coil inductance and geometry, cable length, tuning
       capacitor, damping resistor, and Q-meter serial.
     - Anything in the circuit sheet we can't measure could be estimated offline, by fitting the Court Q-meter model
       (`unh/nmr_sim`) to signal-free Q-curves.
4. **Per-chunk data.**
   - Save every chunk for every event, a sample of events, or only a per-point variance?
   - Every chunk costs disk space, roughly chunks × steps × 2 arrays per event.
5. **Changing the event format.** *Deferred until we're more familiar with PyNMR's outputs.*
   - Should new fields be added alongside the existing keys (easiest to keep JLab-compatible), or should a separate
     UNH training record be written next to each event?
   - Either way, the code goes in `unh/` under a new UNH-HOOK feature, `output-for-training`.
   - Background reading: "Current state in PyNMR" above, and `unh/output_checker/PYNMR_DATA.md` on
     `unh_dev/output_checker`. That file is a field-by-field guide to the event and history files, written for the
     output checker. One correction to it: with EPICS off, `epics` holds `{PV: 0}` for every PV, not `{}`.
6. **Bugs that affect training labels.**
   - Some of the gaps are really bugs:
     - the fixed `wings` value;
     - `area` holding r in FitDeuteron mode;
     - `analysis_completed` always True;
     - the EPICS snapshot taken after the event;
     - the Compare tab changing `daq_type`;
     - bare NaN.
   - Fix them here, or on their own `unh_dev/` branches?
7. **ssRF.** Is there a target design or timeline yet? It sets how much room to leave in the format now (B3–B5).
