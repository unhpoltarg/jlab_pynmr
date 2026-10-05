# `unh/`: UNH Polarized Target group additions

This folder holds code that the UNH fork (unhpoltarg/jlab_pynmr) adds to PyNMR.
JLab does not need it, so it is kept out of the shared code and can be deleted cleanly.

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

## Removing it (e.g. at JLab)

1. Delete the `unh/` folder.
2. Delete the tagged block in `gui/main_window.py`. `git grep UNH-DATA-STREAMER` finds every line.

Step 1 alone is also safe. The hook only imports `unh.data_streamer` if the folder exists, so
without it PyNMR runs exactly as it did before.
