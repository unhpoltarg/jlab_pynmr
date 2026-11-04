# `unh/`: UNH Polarized Target group additions

This folder holds code that the UNH fork (unhpoltarg/jlab_pynmr) adds to PyNMR.
JLab does not need it, so it is kept out of the shared code and can be deleted cleanly.

## UNH features

| Tag | What | UNH files | Hooks in JLab files |
|---|---|---|---|
| `freq-window` | Interactive NMR frequency window on the Run tab | `tests/test_freq_window.py` | `gui/main_window.py`, `gui/tabs/run_tab.py`, `hardware/daq.py` |
| `data-streamer` | Send each finished event to LabView-NMR-Fitter (below) | `data_streamer.py`, `data_streamer.yaml`, `tests/test_data_streamer.py` | `gui/main_window.py` |
| `nmr-sim` | Simulated deuteron NMR as a Test data source, profile `TestSim` ([nmr_sim/README.md](nmr_sim/README.md)) | `nmr_sim/` | `hardware/daq.py`, `pynmr_config.yaml`, `.gitignore` |
| `quad-phase` | Both NMR quadratures: Real/Imag Phase Tunes alternated between events, plus a phase-DAC calibration (below) | `quadrature/`, `tests/test_quadrature.py` | `gui/main_window.py`, `gui/tabs/run_tab.py`, `gui/tabs/base_tab.py`, `pynmr_config.yaml`, `.gitignore` |
| `sweep-blocks` | Sweep counts as a fixed 64 × N: Run-tab Sweeps per Event (N default 10), Tune-tab running average (N default 1); 64-sweep tune chunks | `sweep_blocks.py`, `tests/test_sweep_blocks.py` | `gui/tabs/run_tab.py`, `gui/tabs/tune_tab.py`, `pynmr_config.yaml` |
| `wing-points` | Run tab: "Wing points per side: N" for the wing fit (default from the Analysis-tab bounds), fitted points marked in dashed red | `wing_points.py`, `tests/test_wing_points.py` | `gui/main_window.py` |
| `exit-guard` | Clearer button labels on the exit-while-running dialog | none | `gui/main_window.py` |
| `fork-tools` | Repository tooling for the fork (local Claude Code notes) | none | `.gitignore` |

The freq-window feature mostly lives inside JLab's own files, because it changes how the Run tab and
`MainWindow` handle the Config. Its code is still fully labelled and removable.

## Labelling UNH changes

UNH code goes in `unh/` whenever it can. When a JLab file has to change, every changed line is marked
with one tag, `UNH-HOOK`, and the feature name:

```python
# >>> UNH-HOOK nmr-sim: why this hook exists
elif self.daq_type=='Test' and ...:
    ...
# <<< UNH-HOOK nmr-sim

# >>> UNH-HOOK freq-window: why
# JLab: self.config = Config(self.config_dict['channels'][name], self.settings)
self.replace_config(Config(channel, self.settings))
# <<< UNH-HOOK freq-window

self.pending_window = None   # UNH-HOOK freq-window: a single added line
```

- **Blocks** (`# >>>` ... `# <<<`) hold UNH lines. The same `#` markers work in YAML and `.gitignore`.
- **`# JLab:` lines** keep the JLab lines a block replaced, so removing the block can put them back.
  Prefer adding lines to changing JLab's; a `# JLab:` line is only needed when a JLab line had to go.
- **A trailing `# UNH-HOOK <feature>`** marks a single added line.
- **Only labelled changes.** No reformatting or whitespace clean-up of JLab lines.
- **New features** add their tag and files to `FEATURES` in `strip_unh.py`.
- **Imports of `unh`** in JLab files are lazy or wrapped in `try: ... except ImportError: pass`, so
  PyNMR still runs if `unh/` is deleted.

`git grep -n "UNH-HOOK"` lists every hook, and `python -m unh.strip_unh` lists them by feature.

`tests/test_hooks.py` enforces the labels: it strips every hook from each JLab file this branch changed
and checks that the result is JLab's own version (the last upstream commit merged in). An unlabelled
change, or a new, deleted or renamed JLab file, fails the test. The UNH-owned paths `unh/`,
`changelog/`, `notes/` and `.claude/` are exempt (`.claude/settings.local.json` holds the fork's Claude
Code push guardrails, and JSON can't carry marker comments). So are the files PyNMR rewrites while it
runs (`config/*session.yaml`, `config/*history.json`, `data/recent_baselines.txt`).

## Removing UNH changes

```sh
python -m unh.strip_unh                                # dry run: list every hook
python -m unh.strip_unh --apply                        # remove every hook, restore JLab's lines, delete unh/
python -m unh.strip_unh --feature nmr-sim --apply      # remove one feature, keep the rest
```

The script needs only the standard library. After `--apply`, check the result with `git diff`.

## Data streamer (`data_streamer.py`, `data_streamer.yaml`)

The data streamer sends each finished event's processed NMR line to
[LabView-NMR-Fitter](https://github.com/unhpoltarg/LabView-NMR-Fitter) (`online_fitter/`). It uses
the fitter's existing sweep socket, the same one the legacy UNH LabVIEW VI uses.

### What it does

The streamer runs once per finished event:
- It listens for the existing `EVENT_FINISHED` event-bus message, which `MainWindow.end_finished`
  publishes once per event after the event is written to the eventfile.
- It builds one JSON line in the fitter's `sweep` format (`online_fitter/PROTOCOL.md`) and sends it to
  `host:port` from a worker thread.
- It logs the fitter's reply and shows it in the status bar. Nothing is written to the eventfile,
  history or EPICS.

Two things affect which events go out:
- **Re-analysis:** re-analysing an event on the Analysis tab does not send it again.
- **Species:** only channels whose `species` is listed in `species:` are sent. The default is
  deuteron, because the fitter only fits deuteron lines.

### Failure behaviour

- **Fitter down:** if the fitter is not running, one warning is logged and the event is dropped.
  Each new event tries again, and an info line is logged when the link comes back.
- **Fitter slow:** if the fitter falls behind, the oldest queued event is dropped. The queue holds
  5 events.
- **No impact on acquisition:** acquisition never waits on the streamer.

### Message fields

**Fields the fitter uses:**
- `ts` holds the LabVIEW-style local time, e.g. `6/17/2026 9:31:27 PM`.
- `centfreq_mhz`, `span_mhz` and `npts` are set so that the fitter's
  `centfreq + span*(arange(npts)/npts - 0.5)` reproduces PyNMR's frequency list.
- `raw` holds the averaged phase signal.
- `baseline_sub` holds `fitsub` (baseline- and fit-subtracted). It can be set to `basesub`
  (baseline only) through `signal:`.

**Extra fields** (the fitter ignores these today):
- `source: "pynmr"`
- `freqs_mhz`, the exact axis
- `uniform_axis`
- `basesub` and `fitsub`
- `amplitude_scale`
- `channel`, `cent_freq_mhz` and `mod_freq_khz`
- `sweeps`
- `pynmr_area`, `pynmr_pol` and `pynmr_cc`
- `stop_stamp`

**What comes from where:**
- The frequency axis and window are taken from the event's own `Config`. A centre-frequency or
  width change therefore applies from the event that was started with it.
- `npts` is PyNMR's own point count (`settings.steps`, normally 512). It is not resampled.
- `raw`, `baseline_sub`, `basesub` and `fitsub` are multiplied by `amplitude_scale`.

### Enabling it

Edit `data_streamer.yaml`. Set `enable: True` there to stream in every profile, or enable a single
profile:

```yaml
profiles:
    Deuteron:
        enable: True
```

The fitter binds to loopback only, so by default PyNMR and the fitter must run on the same computer.

### Tests

```sh
conda run -n pynmr --no-capture-output python -m pytest unh/tests
```

### Removing it

`python -m unh.strip_unh --feature data-streamer --apply`. Deleting only `data_streamer.py` is also
safe: the hook in `gui/main_window.py` imports it only if it exists.

## Quadrature phase stepping (`quadrature/`)

This feature records both quadratures of the NMR signal. The operator sets two Phase Tunes, Real and Imag.
While the Run tab's **Quadrature** box is ticked, events alternate between them (0/90, abba, or
0/90/180/270). Each event is still one record in the event file, tagged with `quad_*` fields.

**Auto Calibrate Phase** on the Tune tab steps the phase DAC and fits the angle and gain of each tune.
Calibration files go to `<event_dir>/quad_cal/`.

**Auto Tune** on the Tune tab (`quadrature/autotune.py`): set each tune the sequence uses roughly by hand
(within about 30°), then click it.
- It pauses the Tune loop and steps the phase DAC through 5 values around each tune. It fits the complex
  Q-curve W(f) and moves the tunes to the true angles. Then it starts the Tune loop again.
- 0° is the absorptive direction at the centre frequency. That is the normal to the Q-curve's trace in the
  complex plane there; the absorptive phase turns across the sweep as θ(f) = θ0 + 2 atan((f − f0)/γ).
- The data can't choose between 0° and 180°, or between +90° and −90°; the hand tunes decide.
- It works on the background Q-curve alone. A deuteron line centred in the window doesn't tilt the
  result to first order, and `autotune: mask_khz` can leave bins out.
- A pass is repeated, centred on the new tunes, while a target lies outside the steps around its tune.
  Then one polish pass with tighter steps (±0.5 and ±1 %) around the new tunes gives the final answer.
  Real/Imag take 13 + 13 steps of 64 sweeps, about 50 s on the box.
- The result line gives how far each hand tune was off and each tune's detector gain relative to Real.
  The plot shows the trace with the 0° and 90° directions. **Undo Auto Tune** puts the old tunes back.
- Records go to `quad_cal/autotune_<time>.json` and are never taken for a calibration.

**Run-tab plots** while Quadrature is ticked: a grid replaces JLab's three plots.
- Columns are the stages (Raw Signal, Baseline Subtracted, Fit Subtracted); the top row is Real (0°), the bottom
  row Imag (90°).
- In cycle4, −1 × the 180° record is drawn over every 0° plot and −1 × the 270° record over every 90° plot.
  On the Raw row they sit apart by twice the detector's DC offset.
- A raw curve follows its event live; every other curve changes only when a record at its own angle finishes.

Records at 90/180/270° go to the event file only: they are kept out of EPICS, history and the streamer.

**Baselines** are taken and applied per angle, but selected as in normal mode. Take a baseline run with
Quadrature on, select all its rows at once on the Baseline tab, and press Set Baseline.
- The table gains Angle and Phase DAC (%) columns (after Time), and a line above Set Baseline says what each
  angle will get.
- Its two plots become a 2 × 2 grid: absorptive (0°, −1 × 180°) left, dispersive (90°, −1 × 270°) right; Selected
  Baseline on top, Current Sweep minus Baseline (latest sweep at each angle) below.
- Rows are averaged per angle, and within an angle only at one tune.
- The Run tab shows a "Baselines:" line per angle (red if one is missing or from another tune).
- Records carry `quad_base_ref_deg`, `quad_base_vout` and `quad_base_match`.

**Wing fit size** (feature `wing-points`, `wing_points.py`): a "Wing points per side: N" box in the corner of
the Run tab's Baseline Subtracted plot (and the quadrature grid's Real one) sets the Analysis tab's wing-fit bounds
symmetrically, keeping JLab's outer 1 % skip. The default is what `analysis: wings` gives (148 of 512 points).
A dashed red curve over the yellow fit marks the points used.

**Dispersive records (90/270°)** get a cubic background fitted jointly with the Kramers–Kronig transform of the
latest absorption (`quadrature/dispersion.py`, settings under `dispersion:`). JLab's wing fit eats the
dispersion's long tails. The fitted KK curve is drawn dashed on the Imag Fit Subtracted plot; records carry
`quad_sub_method`, `quad_kk_scale` and `quad_kk_curve`.

The design, record schema, hardware notes (SCPHS-51+ shifter) and the limits of the calibration are in
[`notes/quadrature_phase_design.md`](../notes/quadrature_phase_design.md).

- **Enable:** `quadrature.yaml` (`enable: False`; on for the `TestSimQuad` profile). Enabling only adds the
  controls, and the checkbox starts unticked at every launch.
- **Try it without hardware:** `python pynmr_main.py -p TestSimQuad`. This is the simulator with a
  datasheet-shaped phase shifter.
- **Sample output for readers:** `quadrature/samples/`.
- **Tests:** `unh/quadrature/tests/`, `unh/tests/test_quadrature.py`.
- **Remove:** `python -m unh.strip_unh --feature quad-phase --apply`.

## Tests

All UNH tests, from the repo root:

```sh
conda run -n pynmr --no-capture-output python -m pytest unh -p no:cacheprovider -q
```
