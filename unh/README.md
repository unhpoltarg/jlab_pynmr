# `unh/`: UNH Polarized Target group additions

This folder holds code that the UNH fork (unhpoltarg/jlab_pynmr) adds to PyNMR.
JLab does not need it, so it is kept out of the shared code and can be deleted cleanly.

## UNH features

| Tag | What | UNH files | Hooks in JLab files |
|---|---|---|---|
| `freq-window` | Interactive NMR frequency window on the Run tab | `tests/test_freq_window.py` | `gui/main_window.py`, `gui/tabs/run_tab.py`, `hardware/daq.py` |
| `data-streamer` | Send each finished event to LabView-NMR-Fitter (below) | `data_streamer.py`, `data_streamer.yaml`, `tests/test_data_streamer.py` | `gui/main_window.py` |
| `nmr-sim` | Simulated deuteron NMR as a Test data source, profile `TestSim` ([nmr_sim/README.md](nmr_sim/README.md)) | `nmr_sim/` | `hardware/daq.py`, `pynmr_config.yaml`, `.gitignore` |
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

## Tests

All UNH tests, from the repo root:

```sh
conda run -n pynmr --no-capture-output python -m pytest unh -p no:cacheprovider -q
```
