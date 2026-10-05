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

## 2026-10-05

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
