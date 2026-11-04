# Changelog — UNH fork of jlab_pynmr

A record of what changed in this repository and why. Commit messages say *what*
changed line by line; each entry here gives the overview and the reasoning behind it.

Conventions:
- Newest entries first, one heading per date (`YYYY-MM-DD`).
- Each entry: a short title, **What** changed (files or areas touched), and **Why**.
- Note changes that are local to a clone (git config, hooks) and not tracked in the
  repo, so anyone setting up a fresh clone knows to repeat them.
- History before 2026-10-05 is James Maxwell's upstream work (jdmax/jlab_pynmr). It
  is recorded only in the git log.

---

## 2026-11-04

### Quadrature: split Run-tab plots and Auto Tune (branch `unh_dev/quadrature_phase`)

**What**
- **Run-tab plots while Quadrature is ticked** (`QuadPlots` in `unh/quadrature/ui.py`; no JLab file changed):
  - A 2 × 3 grid replaces JLab's three plots. Columns are Raw Signal, Baseline Subtracted and Fit Subtracted; the top
    row is Real (0°) and the bottom row Imag (90°). The fit and result curves stay where JLab draws them.
  - In cycle4, −1 × the 180° record is drawn over every 0° plot and −1 × the 270° record over every 90° plot.
  - A raw curve follows its event live (JLab's per-chunk update is wrapped). Every other curve changes only when a
    record at its own angle finishes. Unticking shows JLab's three plots again.
- **Sweep counts as 64 × N** (new feature `sweep-blocks`, `unh/sweep_blocks.py`, hooks in `run_tab.py`, `tune_tab.py`
  and `pynmr_config.yaml`): Run-tab Sweeps per Event is 64 × N (N default 10) and the Tune-tab running average 64 × N
  (N default 1). JLab's boxes stay, hidden, and follow. `tune_per_chunk` is 64.
- **Auto Tune** on the Tune tab (new `unh/quadrature/autotune.py`, `AutoTuneThread` in `calibration.py`,
  `autotune:` settings):
  - Steps the phase DAC through 5 values around each hand tune (a local calibration).
  - Fits the trace of the complex Q-curve and moves the tunes to the true 0/90/180/270°. 0° is the absorptive
    direction at the centre frequency.
  - Repeats while a target is outside the steps.
  - Ends with a polish pass (±0.5 and ±1 % DAC around the new tunes) whose answer is final; about 50 s for
    Real/Imag.
  - Pauses and restarts the Tune loop. Has an Undo button.
  - Shows the trace with the 0° and 90° directions. Saves `quad_cal/autotune_<time>.json`.
- **Tuning sweeps 64** (`tune_per_chunk` in `pynmr_config.yaml`, labelled `UNH-HOOK sweep-blocks`; `sweeps_per_step`
  64 for Auto Tune and the calibration). Auto Tune for Real/Imag takes about 25 s, the calibration about 90 s.
- **Defaults from the Hall B cooldown** (`default_tunes` in `quadrature.yaml`): Real 0.514, Imag 0.444, 180° 0.3039,
  270° 0.6031 (phase DAC), the settings of the 2026-10-27 cycle4 run. Used when the saved session has no usable set
  (a non-Real tune missing or equal to Real). A usable saved set still wins.
- **Wing fit as points per side** (new feature `wing-points`, `unh/wing_points.py`, hook in `MainWindow.__init__`):
  - A "Wing points per side: N" box sits in the corner of the Run tab's Baseline Subtracted plot, and of the
    quadrature grid's Real one.
  - N writes the Analysis tab's four wing bounds symmetrically and keeps JLab's outer skip. Those boxes now show
    4 decimals, so a bound isn't rounded to a 5-point step.
  - The default N is what `analysis: wings` gives: 148 of 512 for the shared config, 122 for TestSim.
  - A dashed red curve over the yellow fit marks the points used. For joint-KK records it covers the whole sweep.
  - Changing N redraws the last event's fit at once.
  - Why: Ells wants to set the wing size from the Run tab and judge it by eye.
  - Tests: `unh/tests/test_wing_points.py` (against JLab's own point selection). Simulator: N = 60 gave 60 points
    per side in JLab's fit, the marks followed, and both boxes stayed in step.
- **Exit dialog** (`UNH-HOOK exit-guard`, `ExitDialog` in `gui/main_window.py`): the buttons now read "Ignore. I am an
  expert and I understand the consequences." and "Abort! I didn't mean to make this appear!". Ells's wording; "Abort"
  alone read as the dangerous choice, when it is the one that keeps PyNMR running.
- **Tune-tab plot:** the Auto Tune / calibration plot is about 2.5 times taller (400 px), and the calibration view
  has axis labels (Phase DAC (%), Mean output (V)).
- **Wording:** Calibrate Phase is now **Auto Calibrate Phase**. Tune values read "DAC … %", so they aren't taken for
  signal fractions. A refused Quadrature tick shows its reason in red beside the checkbox (it used to just snap back).
- **Baselines in quadrature mode, selected in one go** (`records.group_baselines`, Baseline-tab hooks, `QuadUI`):
  - The Baseline tab table gains Angle and Phase DAC (%) columns, and a summary above Set Baseline lists each angle's
    rows, sweeps and DAC setting, with problems in red.
  - Within an angle, only rows at one tune are averaged (the latest selected row's); the others are listed.
  - The Baseline tab's two plots become a 2 × 2 grid while quadrature is in use (`BasePlots`): absorptive left,
    dispersive right, −1 × 180°/270° on top of 0°/90°; Selected Baseline above, Current Sweep minus Baseline below.
    The Angle and Phase DAC columns are moved next to Time so they stay in view.
  - The Run tab gains a "Baselines:" status line per angle.
  - An untagged baseline clears the per-angle ones.
  - Records gain `quad_base_vout` and `quad_base_match`.
- **Dispersive background** (new `unh/quadrature/dispersion.py`, `UNH-HOOK quad-phase` in `MainWindow.end_event`,
  `dispersion:` settings): 90/270° records subtract a cubic fitted jointly with the Hilbert (KK) transform of the
  run's latest absorption.
  - The absorption is the latest 0° record, averaged with −1 × the 180° record of the same cycle.
  - The fitted KK curve is drawn dashed on the Imag Fit Subtracted plot.
  - Records gain `quad_sub_method`, `quad_kk_scale` and `quad_kk_curve`.
- **Technote** `notes/nmr_tuning_operation_technote.tex` (and `.pdf`, figures in `notes/figures/`): the operator's
  guide to tuning, Auto Tune, the calibration, quadrature runs, records and troubleshooting, with the physics of
  the trace normal in an appendix.
- **Tests:** `test_quadrature_plots.py` (layout and per-angle updates), trace-fit physics, target choice, and an
  Auto Tune thread run against the simulator. 143 pass.

**Why**
- **Plots:** Ells wants to watch each angle's line change during a run without the angles overwriting one
  another. The −1 × 180°/270° overlays show at a glance whether the opposite settings agree.
- **Baselines:** Ells wants quadrature baselines as easy as normal ones: one selection, applied to each angle.
  - Rows from different angles or tunes must never be averaged together.
  - A missing or stale angle has to be visible before it spoils the data.
  - Simulator: a whole cycle4 baseline run selected at once gave each angle its own baseline at its own tune,
    and every data record used its own angle's baseline.
- **Dispersive background:** the Imag Fit Subtracted plot did odd things in the wings. A wing fit takes the
  dispersion's 1/(f − f_L) tails for background.
  - In the 2026-10-27 hall analysis, the joint fit with KK(absorption) gave a dispersion matching KK to the noise.
  - Simulator: KK scale 1.01 on every 90° record (−1.01 on 270°), with the tails kept.
  - A synthetic test shows the joint fit's residual at least 3 times smaller than a wing fit's.
- **64 × N:** totals that aren't whole box chunks have caused trouble, and a fixed block takes the guesswork out.
- **64 sweeps:** in Run mode the box returned 64 sweeps when asked for 32. Ells asked for 64 in tuning too, to stay clear
  of that limit.
- **Defaults:** the simulator session had every tune at 0 %, so Quadrature couldn't be ticked. Ells asked for the last
  cooldown's tunes as the starting point for now.
- **Auto Tune:** operators can get each tune close by eye, but not exact. Most tuning is done on the background
  Q-curve alone, sometimes with the deuteron line on it. Ells chose the Q-curve circle as the definition of 0°.
- **Why the normal at the centre frequency:**
  - Absorption adds coil resistance and the sweep changes the tank reactance. Both act through the same circuit, so at
    each frequency the absorption points along the normal to the trace there. That is Ells's empirical
    θ(f) = θ0 + 2 atan((f − f0)/γ).
  - The hall-test analysis (2026-10-27) found the deuteron absorption radial to the circle within 2–7°.
  - The resonance point f0 is poorly fixed inside ±200 kHz (normal at the fitted f0: 4° off in a Q ~ 26 test circuit).
    The normal at the window centre doesn't need it.
- **Simulator checks:**
  - The normal at the centre matched the true absorption direction within 0.5° for a straight trace, a Q ~ 26 circle
    and a circle with a λ/2 cable, with the tank detuned up to 200 kHz.
  - Hand tunes 7–32° off came back within 0.25°: pair in 1 pass and 13 steps; cycle4 in 2 passes and 50 steps.
- **Not yet checked on the box.** The 90° angle still rests on the calibration's smooth-gain assumption.
  0° and 180° don't.

## 2026-10-28

### Quadrature after the first hall test (branch `unh_dev/quadrature_phase`)

**What**
- **DAC write timing (fixes events of more than 64 sweeps).** Nothing is written between opening an event's run
  connection and starting its sweeps.
  - Once an event's sweeps are all in, the next event's tune is written on that still-open connection, with the
    Tune tab's latch sequence (`QuadController.after_sweeps`, new hook `UNH-HOOK quad-phase` after the chunk loop in
    `RunThread.execute`).
  - The first event of a run, or the event after a failed one, gets its tune from one short tune-mode connection, as
    `send_to_dac` does (`_write_now`).
  - The hook in `RunThread.setup` is removed.
  - New record field `quad_dac_set`.
- **Calibration:**
  - About 45 s instead of minutes (21 steps per pass, one 32-sweep chunk per step).
  - Live plot of mean phase and diode against the DAC, and a time-remaining readout.
  - Saved during the scan and before the fit. A stop never waits for the fit.
  - Phase unwrapped along v. The clip point is detected from the data.
  - The calibration counts as stale if the centre frequency moves by more than 0.05 MHz.
- **Tune tab:** the quadrature strip now sits under both plots, so the phase and diode plots stay the same size.
- **Tune selection:**
  - "Imag from Calibration" picks whichever of ±90° is nearest the present Imag tune.
  - Turning on cycle4 fills missing 180°/270° tunes from the calibration (opposite Real and Imag).
- **Tests:** 139 pass in total.

**Why**
- **Run-connection writes:** on the box, both 640-sweep events with Quadrature on delivered one 64-sweep chunk and
  timed out, and both had the write on the run connection. 101 one-chunk events were fine. Writing while the box is
  idle avoids re-sending the register before the sweeps.
  - In the simulator, 9 cycle4 events at 640 sweeps (10 chunks each) all completed. The box still needs testing.
- **Calibration speed:** a calibration taking minutes was too slow for the hall.
- **Losing data on close:** closing PyNMR during a calibration force-killed the thread and crashed Python before
  anything was saved.
- **Range and monotonic readout:** the shifter's output clips above about 80 % DAC, and wrapped angles made the
  reported range and monotonic flag wrong.
- **Frequency:** a 32.7 MHz calibration was wrong at 22 MHz, because the shifter's curve depends strongly on
  frequency.
- **Plot sizes:** Ells needs equal-size plots to tune.
- **0°/180° tunes:** they are the easy ones to set by eye.
- **The first hall data:** 16 complete cycle4 cycles on the deuteron line, 2026-10-27, backed up outside the repo.
  - The four settings give I and Q free of detector offsets.
  - The measured dispersion matches the Kramers–Kronig transform of the absorption to about the noise.
  - The Q-curve background is a circle to the noise.
  - The analysis is in that backup's `analysis/` folder.

## 2026-10-27

### Quadrature phase stepping: both NMR quadratures (branch `unh_dev/quadrature_phase`)

**What**
- **New `unh/quadrature/`** (feature `quad-phase`; design in `notes/quadrature_phase_design.md`):
  - Two operator Phase Tunes, Real and Imag (plus 180/270 for cycle4), selected on the Tune tab.
  - A Run-tab **Quadrature** checkbox that alternates events between them: pair, abba or cycle4.
    Each event is tagged with `quad_*` fields.
  - **Calibrate Phase**, which steps the phase DAC and fits the angle and gain of each tune. Results go to
    `<event_dir>/quad_cal/<cal_id>.json`.
  - Per-angle baselines.
  - Settings in `unh/quadrature/quadrature.yaml`: off, except for the new `TestSimQuad` profile.
- **Hooks (`UNH-HOOK quad-phase`):**
  - `gui/main_window.py`: attach; per-angle baseline; EPICS writes and history points for 0° records only;
    `phase_tune_q` (etc.) in the session, with `phase_tune` always the Real tune.
  - `gui/tabs/run_tab.py`: pick the tune before each event; write it on the run thread's own connection;
    restore Real when the run stops.
  - `gui/tabs/base_tab.py`: per-angle baseline averaging.
  - `pynmr_config.yaml`: the `TestSimQuad` profile.
  - `unh/data_streamer.py` skips non-0° records.
- **`unh/nmr_sim/qmeter.py`:** phase-DAC model options, all defaulting to the old behaviour:
  - `phase_dac_curve_deg` and `phase_dac_table`;
  - `phase_dac_gain_slope` and `phase_dac_offset_V`;
  - `phase_dac_tau_ms` settling, on the wall clock (`SimClock.wall_s`);
  - a `phase_dac_v` truth column.
- **Tests:** `unh/quadrature/tests/` (18), `unh/tests/test_quadrature.py` (13), 2 new nmr_sim Q-meter tests.
- **Sample output from the simulator:** `unh/quadrature/samples/`.

**Why**
- The second quadrature is now reconstructed offline by Kramers–Kronig, good to about ±2°. Separating the two
  deuteron transitions needs 0.1–0.2°.
- A Run never sent the phase DAC, and the box only holds what the Tune tab last latched. So the feature writes
  each event's tune on the run's fresh connection: one `set_dac(v, 1)`, the same latch `send_to_dac` relies
  on, then the original 1 ms guard (Ells). No extra box connections are opened.
- Hardware facts from the JLab Q-meter paper (arXiv:2506.14637) and the Mini-Circuits datasheet:
  - the deuteron shifter is an SCPHS-51+ (360°+ at 32.7 MHz, 0–15 V, strongly S-shaped, control bandwidth
    DC–30 kHz, about 0.8 dB insertion-loss swing);
  - the detector is an ADE-1+ mixer fed through it.
  - So the fit leaves the phase free at every DAC value, with a smooth gain and offset.
- Limit, documented: projections fix the reference direction only up to a 2×2 linear map, so a 90° angle
  depends on the smooth-gain assumption.
  - In simulation the angle is exact for constant or linear gain, and 0.2–0.7° off for a gain with
    datasheet-like bumps; the residual flags that case.
  - The PyNMR calibration is for choosing and monitoring the Imag tune. The 0.1° angle should come from the
    offline complex lineshape fit.
- Ells's decisions, 2026-10-27:
  - two operator tunes;
  - 90/180/270° records in the event file only;
  - branch from `unh`, and onto hardware only after `unh_dev/daq_connection` is merged;
  - 1 ms settle;
  - unknown hardware is handled within the existing code's safeties.

## 2026-10-05

### Session summary: start here

This was the first UNH working session on the fork. The detailed entries below explain what changed and why.
This summary says **where** each change lives. The three topic branches
(`unh_dev/data_streamer`, `unh_dev/test_nmr_sim`, `unh_dev/interactive_freq_window`) are merged into `unh`.

**In short**
1. **Repository setup.**
   - The fork moved to `unhpoltarg/jlab_pynmr`, and `unh` became its default branch.
   - Pushes are limited to `unh` and `unh_dev/<topic>` branches.
   - This changelog was started.
2. **Ran on Windows/Anaconda with no code changes.** The program needs its conda environment activated; calling the environment's `python.exe` directly crashes SciPy on this laptop.
3. **Interactive NMR window.**
   - The Run tab now sets the centre frequency and half-width during a cooldown, applied between events.
   - Each event records its own window.
   - `Test` mode now resamples the recorded signal onto the requested window.
4. **Deuteron NMR simulator** (`unh/nmr_sim/`, profile `TestSim`): a physics-based alternative to replaying one recorded event.
5. **Data streamer** (`unh/data_streamer.py`): sends each finished event's line to LabView-NMR-Fitter. Off by default.
6. **All three merged into `unh`, and every UNH change labelled.**
   - Each change to a JLab file is marked `UNH-HOOK <feature>`.
   - `python -m unh.strip_unh` removes any feature, or all of them, and restores JLab's code.
   - `unh/tests/test_hooks.py` fails on any unlabelled change. See `unh/README.md`.

**Commits** (base before this session: `692e3ff`, upstream "Bug fixes")
| Commit | Branch | What |
|---|---|---|
| `5abe854` | `unh` | Changelog started; Claude Code push deny rules; `.gitignore` for local Claude notes |
| `301eb15` | `unh` | Changelog: `unh` made the default branch |
| `059fd62` | `unh` | Changelog: push guard allows `unh_dev/<topic>` |
| `cf25a86` | `unh_dev/interactive_freq_window` | Interactive NMR window, Test-mode resampling, tests, LabVIEW notes |
| `f8f1fcc` | `unh_dev/interactive_freq_window` | First version of this summary |
| `5b0e0ea` | `unh_dev/data_streamer` | Data streamer (`unh/`) |
| `f21810f` | `unh_dev/test_nmr_sim` | nmr_sim and the `TestSim` profile |
| `78f11a2` | `unh` | Merge of `unh_dev/data_streamer` |
| `5e1823e` | `unh` | Merge of `unh_dev/test_nmr_sim` |
| `d41a0ec` | `unh` | Merge of `unh_dev/interactive_freq_window` |
| (next) | `unh_dev/unh_hooks`, then merged into `unh` | `UNH-HOOK` labels, nmr_sim moved into `unh/`, `strip_unh.py`, `test_hooks.py`, this summary updated |

**Where each change lives**
| Feature (tag) | UNH files | Hooks in JLab files |
|---|---|---|
| `freq-window` | `unh/tests/test_freq_window.py` (7 tests) | `gui/main_window.py`: `__init__` (`pending_window`), `save_session`, `channel_change`, and the new `replace_config`, `run_in_progress`, `set_window`, `apply_pending_window`. `gui/tabs/run_tab.py`: `__init__` (window inputs), `start_thread`, `combo_changed`, and the new `update_window_label`, `window_apply_pushed`. `hardware/daq.py`: Test replay resampled onto the window. |
| `data-streamer` | `unh/data_streamer.py`, `unh/data_streamer.yaml`, `unh/tests/test_data_streamer.py` (21 tests) | `gui/main_window.py`: `__init__`, one block |
| `nmr-sim` | `unh/nmr_sim/` (38 tests) | `hardware/daq.py`: three blocks. `pynmr_config.yaml`: the `TestSim` profile. `.gitignore`: two lines. |
| `fork-tools` | none | `.gitignore`: the local Claude notes |
| (fork as a whole) | `changelog/changelog.md`, `notes/labview_panel_differences.md`, `unh/README.md`, `unh/strip_unh.py`, `unh/tests/test_hooks.py` (9 tests) | `.claude/settings.local.json`, `permissions.deny`: stops Claude Code skipping hooks, force-pushing, or pushing to `upstream` |

**To find these:**
- `git grep -n "UNH-HOOK"` lists every hook; `git grep -n "UNH-HOOK freq-window"` lists one feature.
- `python -m unh.strip_unh` (a dry run) lists them by file, line and feature.
- `git log --oneline 692e3ff..unh` lists this session's commits; `git diff 692e3ff..unh -- <file>` shows one file's changes.

**Local only, not in git** (repeat these in any new clone; the details are in the entries below)
- `.git/hooks/pre-push`: allows only `unh` and `unh_dev/*` to go to unhpoltarg.
- Git config:
  - `remote.pushDefault=origin` and `push.default=upstream`;
  - the `upstream` (jdmax) push URL is set to `DISABLED`;
  - `origin` points to `unhpoltarg/jlab_pynmr`.
- Conda environment `pynmr` (Python 3.12):
  - built from conda-forge, plus nidaqmx, RsInstrument and labjack-ljm from pip;
  - launch it with `conda run -n pynmr --no-capture-output python pynmr_main.py`.
- `.claude/CLAUDE.md` holds local Claude notes; `.claude/reference/labview_nmr_panel.png` is the LabVIEW screenshot.

**Open items**
- **Before analysing cooldown data with window changes:**
  - CC doesn't transfer between widths;
  - baselines aren't checked for a matching window;
  - wings are fractions of the sweep;
  - history points don't record the window;
  - the deuteron fit's `wL` start value doesn't follow the centre.
- **Decision pending:** carry CC over on channel change, or load a per-channel CC.
- **Existing exit crash:** `core/thread_manager.py:182`, after a run. It also happens on unmodified `unh`, and data is saved first.
- **Other known bugs:** "Use TE" writes to a `te/` folder that doesn't exist; `explore_tab.py` uses a PyQt5-only call; pytest can't collect anything under `utils/`.

### Merged the three topic branches; every UNH change labelled and removable (branch `unh_dev/unh_hooks`)

**What**
- **Merged into `unh`** with `--no-ff`, least invasive first: `unh_dev/data_streamer`, `unh_dev/test_nmr_sim`,
  then `unh_dev/interactive_freq_window`. Only this changelog conflicted; the entries were combined by hand.
- **One label for every UNH change to a JLab file:** `# >>> UNH-HOOK <feature>` ... `# <<< UNH-HOOK <feature>`
  blocks, or a trailing `# UNH-HOOK <feature>` on a single added line.
  - The features are `freq-window`, `data-streamer`, `nmr-sim` and `fork-tools`.
  - A JLab line that a block replaced is kept inside the block as `# JLab: <line>`.
  - This replaces the older `UNH-DATA-STREAMER` and `nmr_sim hook` tags.
  - The window feature had no labels before. Its code is unchanged except in two places:
    - `save_session` now adds the window to the saved dict after JLab's dict is built, so JLab's lines stay as they were.
    - Whitespace-only edits to JLab lines in `gui/tabs/run_tab.py` and `hardware/daq.py` were undone.
- **Moved into `unh/`:** `nmr_sim/` is now `unh/nmr_sim/` (`python -m unh.nmr_sim`;
  the `hardware/daq.py` hook imports `unh.nmr_sim.adapter`), and `tests/test_freq_window.py` is now
  `unh/tests/test_freq_window.py`. Imports and relative paths in the tests were updated to match.
- **New `unh/strip_unh.py`:** removes all UNH changes, or one feature with `--feature <tag>`. It deletes
  the blocks, puts the `# JLab:` lines back, and deletes the feature's files (or all of `unh/`).
  It does a dry run unless given `--apply`, and needs only the standard library.
- **New `unh/tests/test_hooks.py`:** strips the hooks from every JLab file this branch changed and
  checks that the result equals JLab's version (the merge-base with `upstream/master`). Unlabelled
  edits fail, and so do new, deleted or renamed JLab files.
  - Exempt: UNH-owned paths (`unh/`, `changelog/`, `notes/`, `.claude/`) and the files PyNMR rewrites
    while it runs.
  - It also checks the marker syntax, that each feature still hooked in has its `unh/` files, and that
    Python still compiles after removing each feature.
- **Docs:** `unh/README.md` now has the feature list, the labelling rules and the removal steps.
  `unh/nmr_sim/README.md` and the data streamer's hook tests use the new tags.

**Why**
These features change JLab's code for UNH purposes. With one tag, `git grep -n "UNH-HOOK"` finds every
change, and the `# JLab:` lines mean the original code can be put back exactly, not just deleted around.
The test keeps that true for future work, and the script turns removal into one command.

**Checked before merging** (headless runs in throwaway worktrees):
- **All features together:**
  - In `Test` and `TestSim`, a window change requested mid-run showed as pending and applied from the
    next event. Each DAQ connection, including the simulator, used that event's window, and the
    session file saved it.
  - With the headless fitter running, the streamer sent each `TestSim` event with its own window, and
    all replies were `ok`.
- **Everything stripped:** the JLab files matched `upstream/master` exactly. The only remaining
  differences were `changelog/`, `notes/` and `.claude/settings.local.json`, and the `Test` profile
  ran events normally.
- **One feature stripped at a time** (`freq-window`, `data-streamer`, `nmr-sim`): the remaining UNH
  tests passed, and the remaining features ran headless.

### Deuteron NMR simulator as an alternative Test-mode data source (`nmr_sim/`, profile `TestSim`)

*Branch `unh_dev/test_nmr_sim`.*

**Summary**
Test mode can now run a physics simulation of a deuteron target instead of replaying one
recorded event. Choose the new **TestSim** profile at startup, or launch with `-p TestSim`;
the existing **Test** profile still replays exactly as before.

The simulator produces sweeps from:
- the Dulya lineshape, ported from optimized-mcclellan-fits
- a Liverpool-style Q-meter
- a scripted run: an off-resonance baseline, then TE, spin-up and T1 relaxation, at
  wall-clock speed × a speed factor
- realistic noise

Everything is set in the `nmr_sim:` block of the TestSim profile. The code lives in one new
folder, `nmr_sim/`. It touches the rest of PyNMR in only three files, at blocks tagged
`nmr_sim hook`.

**Files changed: where to find them after the merge**

Run `git grep -n "nmr_sim hook"` to list every connection point. The line numbers below
are from the commit on `unh_dev/test_nmr_sim` and may shift after the merge; the tags and
anchors won't.

| File | Status | Where | Find it by |
|---|---|---|---|
| `nmr_sim/` (whole folder) | **new** | top level of the repo | the folder itself |
| `hardware/daq.py` | modified | `DAQConnection.__init__`: an `elif` before the replay `elif self.daq_type=='Test':` branch (~L53–60) | `nmr_sim hook (1/3)` |
| `hardware/daq.py` | modified | `DAQConnection.get_chunk`: an `elif` before the replay Test branch (~L121–124) | `nmr_sim hook (2/3)` |
| `hardware/daq.py` | modified | `DAQConnection.set_dac`: an `if` before the replay Test `return True` (~L144–147) | `nmr_sim hook (3/3)` |
| `pynmr_config.yaml` | modified | `profiles:`, new `TestSim:` profile between `Test:` and `Deuteron:` (~L168–218) | `# --- nmr_sim hook` … `# --- end nmr_sim hook` |
| `.gitignore` | modified | end of file: `config/sim_session.yaml`, `config/sim_history.json` (~L30–32) | `# nmr_sim hook` |
| `changelog/changelog.md` | modified | this entry | — |

The new files in `nmr_sim/` are:
- **Code:** `__init__.py`, `__main__.py`, `adapter.py`, `clock.py`, `lineshape.py`, `noise.py`,
  `params.py`, `qmeter.py`, `simulator.py`, `susceptibility.py`, `timeline.py`
- **Docs:** `README.md`
- **Tests:** `tests/__init__.py`, `tests/test_isolation.py`, `tests/test_lineshape.py`,
  `tests/test_noise.py`, `tests/test_qmeter.py`, `tests/test_simulator.py`,
  `tests/test_timeline.py`

Nothing in `core/`, `gui/`, `config/` or `utils/` was changed. The `replay` code paths in
`hardware/daq.py` are untouched, apart from whitespace on the lines next to the hooks.

**Files created at run time (all gitignored)**
- `config/sim_session.yaml`, `config/sim_history.json`: TestSim session and history
- `log/nmr_sim_truth_<UTC>.csv`: true P and Q for each chunk
- the usual `data/current_*.txt` event files

**What**
- **New self-contained package `nmr_sim/`.** It is NumPy only and imports nothing
  from PyNMR (`core/`, `gui/`, `hardware/`, `config/`, `utils/`, PySide6); a test enforces
  this. Signal path: simulated clock → scripted timeline → susceptibility χ → Q-meter →
  phase and diode detectors → noise.
  - `lineshape.py` ports the Dulya spin-1 deuteron model (`FastModel`, `MATERIALS`)
    from `optimized-mcclellan-fits/fitter/deuteron_model.py` at commit `0f4b4a8`. The
    port matches the source to 1e-12. Two additions: a closed-form `r_of_P` and a
    `FastModel.parts`. The hole-burning (`*_rev`/`bump`) and non-Boltzmann parts were left out.
  - `susceptibility.py` builds χ_eff = 4πη(χ′ − iχ″) from the model's absorptive and
    dispersive curves. The dispersion sign is fixed by a Kramers–Kronig test.
  - `qmeter.py` is a constant-current series Q-meter after Court et al., NIM A 324 (1993) 433.
    - The coil is L₀(1+χ_eff), behind a lossy λ/2 cable, with a tuning capacitor and damping resistor.
    - Phase-sensitive and diode outputs.
    - The capacitor auto-tunes, and the gains are calibrated to the replay levels.
    - The Tune-tab DACs act as a varactor and a reference-phase shift.
  - `timeline.py` provides `hold`, `spinup` (τ) and `relax` (T1) segments plus spin-1 P_TE. A
    segment can move the line out of the window, which is how the baseline segment works.
  - `clock.py` (wall time × speed), `noise.py` (Gaussian σ/√N, optional drift), `params.py`
    (defaults; unknown keys raise), and `simulator.py` (process singleton, truth CSV
    `log/nmr_sim_truth_<UTC>.csv`).
  - `adapter.py` (`SimDAQ`) implements the DAQ chunk contract. `python -m nmr_sim`
    prints a configuration summary.
  - `README.md` covers usage, assumptions and limits. `tests/` holds 48 tests; run them with
    `python -m pytest nmr_sim/tests -p no:cacheprovider -q`.
- **Connection points into PyNMR.** These are the only PyNMR edits. Each is tagged `nmr_sim hook`;
  list them with `git grep -n "nmr_sim hook"`.
  1. `hardware/daq.py`, three blocks in `DAQConnection`. Replay code is unchanged.
     - (1/3) `__init__`: an `elif` that lazily imports `nmr_sim.adapter.SimDAQ` when
       `settings['test_source'] == 'sim'`.
     - (2/3) `get_chunk`: an `elif` that returns simulator chunks.
     - (3/3) `set_dac`: forwards the Tune-tab DACs to the simulator.
  2. `pynmr_config.yaml`: a new `TestSim` profile with `test_source: sim`, its own
     `sim_session`/`sim_history` files, `d_fit_params` near the ND3 preset, and an `nmr_sim:` block.
     The existing `Test` profile still replays.
  3. `.gitignore`: `config/sim_session.yaml` and `config/sim_history.json`.

  **To remove nmr_sim:** delete `nmr_sim/` and the three tagged hooks.
- **Defaults to revisit** with real UNH values:
  - Material is ND3, single bond, to match PyNMR's single-bond fit.
  - Amplitude: 8e-4 V phase-signal peak at P = 0.19 %. This assumes the replay event's `pol`
    is in percent, which is uncertain.
  - Q-meter components were chosen to reproduce the replay's nearly flat Q-curve, which needs
    a coil Q of about 2. They are not measured values.
- **Verified headless.** The Test profile replays as before. TestSim runs through
  `DAQConnection` and through the full GUI (run offscreen).
  - Baseline-segment events were taken and set as the baseline, and they subtract cleanly.
  - TE signal is visible above the noise. Area tracks the true P linearly to within 4 %.
  - PyNMR's own `deuteron_fits.fit` recovers the true P to 0.1–0.2 % at P ≈ 40 %.
- **TODO:** hole burning. Also noted: with η > 0, PyNMR's `FitDeuteron` takes about 25 s per
  event in the GUI, and its fit can land in a local minimum if `r` starts near 1.

**Why**
The replay Test source has four problems:
- It can't provide a real baseline, because every chunk contains the signal.
- P never changes.
- It draws a 31.83 MHz recording on the 32.7 MHz channel axis.
- Its noise is biased and grows with the sweep count.

A physics-based simulator lets baseline handling, analysis, fitting and P tracking be tested
end to end without hardware. It is kept separate, with the connection points listed above,
so it can be removed or reworked later without touching PyNMR.

### Stream the processed NMR line to LabView-NMR-Fitter (branch `unh_dev/data_streamer`)

**Summary**
- **New `unh/` folder** (UNH-only): `data_streamer.py`, `data_streamer.yaml` (off by default, can be
  enabled per profile), `README.md`, and 26 tests.
- **What is sent:** after each event, PyNMR sends the event's averaged `fitsub` line to the fitter's
  loopback socket (`127.0.0.1:8777`), in the LabVIEW VI's JSON format.
  - Points: PyNMR's own 512 points.
  - Frequency window: taken from each event's own settings, so window changes apply from the next
    event.
  - Channels: deuteron only.
- **Fitter reply:** shown in the status bar and the log. The eventfile, history and EPICS are
  unchanged.
- **Failures:** if the fitter is down, PyNMR logs one warning and keeps acquiring.
- **Shared code:** the only change is a six-line hook in `MainWindow.__init__`, tagged
  `UNH-DATA-STREAMER`. To remove the feature, delete `unh/` and those lines; deleting the folder
  alone is also safe.
- **Tested:** a live GUI run (PyNMR Test profile and the fitter, about 50 minutes) gave 782 fits with
  no errors. With `unh/` removed, PyNMR ran normally.
- **Still open:** amplitude units (`amplitude_scale`) need real UNH hardware data.

**What**
- New `unh/` folder for UNH-only additions:
  - `data_streamer.py` holds the streamer code.
  - `data_streamer.yaml` holds its settings. Streaming is off by default and can be enabled per
    `-p` profile.
  - `README.md` says how to enable and remove it.
  - `tests/test_data_streamer.py` has 26 tests.
- **What gets sent:** after each event is analysed and written, the event's line goes to the fitter's
  existing loopback sweep socket (`127.0.0.1:8777`). This is the same JSON format the UNH LabVIEW VI
  sends.
  - The fitter's `baseline_sub` field carries `fitsub` (baseline- and fit-subtracted, averaged over
    the event's sweeps). A setting switches it to `basesub`.
  - Extra fields the fitter ignores today: `source`, `freqs_mhz`, `basesub`/`fitsub`, `sweeps`, and
    PyNMR's area/pol/CC.
- **Fitter reply:** logged and shown in the status bar. Nothing goes into the eventfile, history or
  EPICS.
- **Window:** taken from each event's own `Config`, so a change made with the Run-tab window controls
  (`unh_dev/interactive_freq_window`) applies from the next event. `npts` is PyNMR's own 512 points,
  not resampled.
- **Channels:** only deuteron channels are sent.
- **Network failures:** sends happen on a worker thread with a 5-event drop-oldest queue. A missing
  fitter logs one warning and never stalls acquisition.
- **Changes to shared code:** one six-line block in `MainWindow.__init__`, tagged `UNH-DATA-STREAMER`.
  It subscribes the streamer to the existing `EVENT_FINISHED` bus event. `pynmr_config.yaml` is not
  changed.

**Why**
- LabView-NMR-Fitter is the UNH "patch" fitter that fits lines from the legacy LabVIEW NMR software.
  Feeding it from PyNMR lets one fitter serve both DAQs.
- The streamer may never be used at JLab, so it is isolated. At JLab, delete `unh/` and the tagged
  block (`git grep UNH-DATA-STREAMER`). Deleting just the folder is also safe: the hook's import then
  fails quietly and PyNMR runs as before.
- **Checked end to end** against the real fitter, run headless in equilibrium mode:
  - PyNMR in the Test profile streamed 4 events and received fits;
  - the fitter's 8778 publish stream carried 512-point lines on PyNMR's axis;
  - the streamer stopped cleanly on close.

  With `unh/` removed, PyNMR ran and closed normally.
- **Open:** the amplitude units still need checking with real PyNMR data from the UNH hardware.
  - The fitter's `scale` preset and bound assume LabVIEW volts. PyNMR's phase is ADC/`phase_cal`.
  - `amplitude_scale` in `data_streamer.yaml` is the knob on this side.
  - Matching changes on the fitter side (explicit axis, MHz-based wing widths, per-source units,
    window-change handling, source tagging) are being made in that repo.

### Interactive NMR frequency window on the Run tab (branch `unh_dev/interactive_freq_window`)

**What**
- `gui/tabs/run_tab.py`: the NMR Settings box has new **Center Freq (MHz)** and
  **Half-width ± (kHz)** inputs and an **Apply Window** button.
  - The inputs stay editable during a run.
  - The label under the channel selector shows the active window and any pending change.
  - Selecting a channel resets the fields to that channel's values from the config file.
- `gui/main_window.py`: new `set_window()`, `apply_pending_window()`, `replace_config()` and
  `run_in_progress()`.
  - **When idle,** a change applies immediately and reprograms the R&S.
  - **During a run,** it is held and applied by `RunTab.start_thread` just before the next event starts.
    The event in progress keeps its window. The FPGA gets the new frequency table automatically,
    because each event's DAQ connection sends it.
  - **Every change builds a new `Config` from a copy of the channel settings.** Events keep a
    reference to their own Config, so editing the shared one would rewrite the frequency axis
    of events already taken.
  - **Run settings carry over:** Sweeps, CC and the phase/diode tune values carry over on window
    *and channel* changes. Before, a channel change silently reset Sweeps to 640 and CC to −0.08,
    while the Run tab still showed the old values.
  - **Logging:** every change goes to the log and the status bar.
  - **Session file:** the window is saved in `config/<session>.yaml` (`cent_freq`, `mod_freq`) and
    restored at startup when the saved channel matches.
- `pynmr_config.yaml` can take an optional `settings.window_limits` with `cent_min`,
  `cent_max`, `hw_min_khz` and `hw_max_khz`. These are the input bounds. Code defaults
  (1–500 MHz, 1–2000 kHz) apply if it's absent; set it to match the R&S FM deviation limits.
- `hardware/daq.py` (**Test mode only**): the simulated DAQ now returns the recorded test signal
  *at the frequencies the window asks for*.
  - The recording is `utils/d_signal_event.txt`: deuteron, 31.43–32.23 MHz.
  - It is interpolated onto the current window's frequency points.
  - Points outside the recorded range hold the nearest recorded edge value, with the usual
    test noise added. The off-recording part therefore looks like flat baseline instead of a jump
    to zero, which kept the plots readable when the window is moved past the recording.
  - Before, the same 512 recorded points were replayed on whatever axis the channel set, so a
    deuteron line appeared at 212.9 MHz on the Proton5T channel.
  - A window equal to the recording's own (31.83 MHz ± 400 kHz) gives back the original signal exactly.
- `tests/test_freq_window.py`: new tests covering:
  - the frequency axis and the FPGA table;
  - idle versus between-event application;
  - no in-place changes to an existing config, and carry-over of settings;
  - Test-mode interpolation and edge-hold outside the recording.

  It is kept outside `utils/` because `utils/__init__.py` breaks pytest collection.

**Why**
During a cooldown UNH needs to move the NMR window without restarting:
- the field is rarely exactly 5 T, so the Larmor frequency shifts;
- ND3, d-butanol and d-propanediol have different quadrupole widths.

The width is entered as a **half-width (±kHz)**, with the same meaning as `mod_freq`, so the
config file and the Run tab agree. The old UNH LabVIEW panel's "Freq Span" is a **full** width,
so the factor of 2 matters when comparing the two. Each event still writes its own `freq_list`
and window to the event file, so data from a cooldown with window changes can be analysed
event by event afterwards.

**Known gaps (separate decisions, not in this change)**
- **Calibration:** area is a plain sum over bins, so it depends on bin width. A CC measured with
  one width doesn't transfer to another.
- **Baselines:** they aren't checked for a matching window.
- **Wings and integration ranges:** they are sweep fractions, so they move with the window.
- **History points:** they don't record the window.
- **Fit start values:** the Deuteron fit's `wL` start value doesn't follow the center.

### LabVIEW panel reference notes

**What**
- New `notes/labview_panel_differences.md`: features of the old UNH LabVIEW NMR panel that
  PyNMR lacks or does differently, for later work.
- `.gitignore`: added `.claude/reference/`. The LabVIEW screenshot the notes are based on is
  kept locally at `.claude/reference/labview_nmr_panel.png` and is not shared through git.

**Why**
To keep a record of the quality-of-life features UNH wants to bring over, so they can be
taken up one at a time.

### Push guard allows per-topic development branches (`unh_dev/<topic>`)

**What**
- `.git/hooks/pre-push` now allows pushing `unh` and `unh_dev/<topic>` to
  `unhpoltarg/jlab_pynmr`. The hook is local to a clone and not tracked in the repo.
  Everything else is still blocked: `master`, `testing`, tags, other branch names, and any
  push to `jdmax/jlab_pynmr`.

**Why**
To give experimental work a place where it can break things without touching `unh`.
`unh` stays the stable, runnable branch. Development uses one branch per topic, named
`unh_dev/<topic>` (for example `unh_dev/te-fix`) and branched from `unh`. Each topic branch
is pushed to GitHub as a backup and is merged back into `unh` (`git merge --no-ff`) once
it works. A plain `unh_dev` branch is not used, because git cannot hold `unh_dev` and
`unh_dev/<topic>` at the same time.

### `unh` is now the default branch of the fork

**What**
- On GitHub, set the default branch of `unhpoltarg/jlab_pynmr` to `unh` (was `master`).
  `jdmax/jlab_pynmr` is unchanged and still defaults to `master`.
- In the local clone, updated `origin/HEAD` to point at `origin/unh`
  (`git remote set-head origin -a`).

**Why**
`unh` is where all UNH work happens. With it as the default, new clones check it out,
the repo page shows it, and new in-fork pull requests target it. Nobody has to remember
to switch away from `master`.

### Repository moved to the unhpoltarg organization; pushes restricted to `unh`

**What**
- Transferred the fork from `ellie-long/jlab_pynmr` to `unhpoltarg/jlab_pynmr` on
  GitHub. The fork relationship to `jdmax/jlab_pynmr` is kept.
- Local clone setup (not tracked in the repo; repeat it in any new clone):
  - `origin` → `https://github.com/unhpoltarg/jlab_pynmr.git`
  - `upstream` (`jdmax/jlab_pynmr`) is fetch-only: its push URL is set to `DISABLED`.
  - `remote.pushDefault=origin` and `push.default=upstream`
  - `.git/hooks/pre-push` rejects any push other than `refs/heads/unh` to
    `unhpoltarg/jlab_pynmr`. That includes tags and pushes to other branches.
- `.claude/settings.local.json`: added `deny` rules so Claude Code cannot skip git
  hooks (`--no-verify`), force-push, or push to `upstream`.

**Why**
UNH polarized-target development should be kept separate from upstream.
- All UNH work lives on the `unh` branch under the group's GitHub organization, not
  a personal account.
- Nothing should be pushed by accident to `master` or to James Maxwell's original
  repository.
- Commits are still authored as `Elena Long <ellie@jlab.org>`, which GitHub credits
  to the `ellie-long` account.

### Local Claude Code notes file (gitignored)

**What**
- `.gitignore`: added `.claude/CLAUDE.md`.
- Created `.claude/CLAUDE.md` in the local clone. It is not tracked. It holds the repo rules
  (push only to `unh`, keep this changelog current), the fresh-clone git setup including
  the pre-push hook script, and a short codebase orientation.

**Why**
It gives Claude Code a durable place in the repo for its working context and rules.
Ignoring it keeps machine-specific notes out of the shared history.

### Changelog added

**What**
- New `changelog/changelog.md` (this file).

**Why**
To keep a readable, human-level history of changes and the reasons for them,
alongside commit messages.
