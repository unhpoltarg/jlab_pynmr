# `unh/`: UNH Polarized Target group additions

This folder holds code that the UNH fork (unhpoltarg/jlab_pynmr) adds to PyNMR.
JLab does not need it, so it is kept out of the shared code and can be deleted cleanly.

## UNH features

| Tag | What | UNH files | Hooks in JLab files |
|---|---|---|---|
| `freq-window` | Interactive NMR frequency window on the Run tab | `tests/test_freq_window.py` | `gui/main_window.py`, `gui/tabs/run_tab.py`, `hardware/daq.py` |
| `data-streamer` | Send each finished event to LabView-NMR-Fitter (below) | `data_streamer.py`, `data_streamer.yaml`, `tests/test_data_streamer.py` | `gui/main_window.py` |
| `nmr-sim` | Simulated deuteron NMR as a Test data source, profile `TestSim` ([nmr_sim/README.md](nmr_sim/README.md)) | `nmr_sim/` | `hardware/daq.py`, `pynmr_config.yaml`, `.gitignore` |
| `daq-link` | Close the FPGA box connections cleanly, stop the box after errors, log box errors (see below) | `tests/test_daq_link.py` | `hardware/tcp.py`, `hardware/udp.py`, `hardware/daq.py`, `gui/tabs/run_tab.py`, `gui/tabs/tune_tab.py`, `pynmr_config.yaml` |
| `lab-env` | Run instructions for the UNH DAQ computer: `conda activate pynmr312` (see below) | none | `README.md` |
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

Streaming is **on by default** (since 2026-11-04): the shipped `data_streamer.yaml` has `enable: True`.
That is harmless when no fitter is running (see Failure behaviour). If the settings file is missing or
broken, the built-in default (`enable: False` in `data_streamer.py`) leaves streaming off.

To turn it off everywhere, set `enable: False` in `data_streamer.yaml`. To turn it off for one profile only:

```yaml
profiles:
    Proton:
        enable: False
```

The fitter binds to loopback only, so by default PyNMR and the fitter must run on the same computer.

### Tests

```sh
conda run -n pynmr --no-capture-output python -m pytest unh/tests
```

### Removing it

`python -m unh.strip_unh --feature data-streamer --apply`. Deleting only `data_streamer.py` is also
safe: the hook in `gui/main_window.py` imports it only if it exists.

## Box connection (`daq-link`)

PyNMR opens a new TCP and UDP connection to the FPGA box (`fpga_settings: ip`) for every event, every tune
session and every DAC change on the Tune tab, and closes it again afterwards. In JLab's code a connection
is closed only when Python garbage-collects it, and nothing tells the box to stop sweeping when a read
times out or Tune is stopped. A connection that Windows closes while the box's data is still unread is
aborted (reset), not closed normally. At UNH the box sometimes stopped answering until it was power cycled,
which fits its network stack getting stuck on one of those aborted connections.

The hooks:
- `TCP.close()` sends the box a normal close, reads off anything it is still sending, and waits up to
  `fpga_settings: close_wait` s (default 0.5) for the box to close its side. `UDP.close()` and
  `DAQConnection.close()` close everything; the Run thread, Tune thread and Tune DAC changes call them.
- The Run thread sends the stop-sweep command after a read error, and the Tune thread sends it whenever
  tune ends (Stop or error), before closing.
- The box's refusals ("Set register error", "Set frequency error") and UDP failures, which JLab only
  prints to the console, also go to the log file.
- Each close is logged, e.g. `DAQ connection closed: box closed its side after 3 ms`. If the log says
  `box did not close its side within 0.5 s`, each event is 0.5 s slower; lower `close_wait` if that matters.

Tests: `tests/test_daq_link.py` (fake box on 127.0.0.1). Remove with
`python -m unh.strip_unh --feature daq-link --apply`.

## Python environment: `conda activate pynmr312` (`lab-env`)

Run PyNMR on **Python 3.12 or newer**. On the UNH DAQ computer (Linux/WSL) that is the conda env `pynmr312`:

```sh
conda deactivate          # repeat until no env is active; stacked envs can leave the old Python first on PATH
conda activate pynmr312
python --version          # must say 3.12 or newer
python pynmr_main.py -p Deuteron
```

Run the fitter (LabView-NMR-Fitter) on Python 3.12 too.

Why it matters: on the old Python 3.11 env (`pynmr`, kept on that computer only for rollback), PyNMR died
silently in the middle of runs, most often with the data streamer on. The cause was
`Fatal Python error: none_dealloc: deallocating None`, raised in the main thread while pyqtgraph redrew the Analysis
plots. Python 3.12 never deallocates None (PEP 683), so that crash can't happen there. Since PyNMR died mid-sweep,
the deuteron box was left stuck until it was power cycled. The `daq-link` change does not prevent this; the
Python 3.12 env does.

## Tests

All UNH tests, from the repo root:

```sh
conda run -n pynmr --no-capture-output python -m pytest unh -p no:cacheprovider -q
```
