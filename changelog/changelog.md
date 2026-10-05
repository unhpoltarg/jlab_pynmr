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

### Session summary: start here

This was the first UNH working session on the fork. The detailed entries below explain what changed and why.
This summary says **where** each change lives, so it can still be found after
`unh_dev/interactive_freq_window` is merged into `unh`.

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

**Commits** (base before this session: `692e3ff`, upstream "Bug fixes")
| Commit | Branch | What |
|---|---|---|
| `5abe854` | `unh` | Changelog started; Claude Code push deny rules; `.gitignore` for local Claude notes |
| `301eb15` | `unh` | Changelog: `unh` made the default branch |
| `059fd62` | `unh` | Changelog: push guard allows `unh_dev/<topic>` |
| `cf25a86` | `unh_dev/interactive_freq_window` | Interactive NMR window, Test-mode resampling, tests, LabVIEW notes |
| (this commit) | `unh_dev/interactive_freq_window` | This summary |

**Files changed in git** (line numbers as of `cf25a86`; a fast-forward merge keeps them)
| File | Where | What |
|---|---|---|
| `gui/main_window.py` | `__init__` L73 | New `self.pending_window` (window waiting for the next event) |
| | `save_session` L217 | Saves `cent_freq` and `mod_freq` to the session yaml |
| | `channel_change` L369 | Copies the channel dict; restores the session window at startup; uses `replace_config` |
| | `replace_config` L385 (new) | Swaps in a new Config, carrying over Sweeps, CC and tune voltages |
| | `run_in_progress` L402 (new) | True while sweeps run or another event will start |
| | `set_window` L408 (new) | Requests a window: applied now if idle, otherwise pending |
| | `apply_pending_window` L423 (new) | New Config, reprograms the R&S, logs the change |
| `gui/tabs/run_tab.py` | `__init__` L159 (`# NMR window:` block) | Center Freq and Half-width inputs plus the Apply Window button in the NMR Settings box |
| | `start_thread` L399 | Applies a pending window before `new_event()` |
| | `combo_changed` L430 | Resets the window fields to the selected channel's values |
| | `update_window_label` L437 (new) | Shows the active window and any pending one |
| | `window_apply_pushed` L446 (new) | Validates the inputs, then calls `MainWindow.set_window` |
| `hardware/daq.py` | `DAQConnection.__init__` Test branch L62 | Interpolates the recorded test signal onto the window; holds edge values outside it |
| `tests/test_freq_window.py` | new file, 7 tests | Window axis, FPGA table, idle/pending apply, no config mutation, carry-over, Test resampling |
| `notes/labview_panel_differences.md` | new file | UNH LabVIEW panel features to bring over later |
| `changelog/changelog.md` | new file | This changelog |
| `.gitignore` | L23–25 | Ignores `.claude/CLAUDE.md` and `.claude/reference/` |
| `.claude/settings.local.json` | `permissions.deny` | Stops Claude Code skipping hooks, force-pushing, or pushing to `upstream` |

**To find these after merging:**
- `git log --oneline 692e3ff..unh` lists this session's commits.
- `git show cf25a86` shows the full window change.
- `git diff 692e3ff..unh -- <file>` shows one file's changes.
- `git grep -n "pending_window\|NMR window"` finds the window code.

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
