# PyNMR

A Python-based NMR polarimetry control and data acquisition system for polarized target experiments at Jefferson Lab. PyNMR drives real-time RF sweeps, acquires phase and diode signals from an FPGA or NI DAQ, computes baseline-subtracted polarization, and writes results back to the EPICS slow-controls network.

---

## Features

- **Multi-species support** — proton and deuteron channels with per-profile frequency and power settings
- **Multiple DAQ backends** — FPGA (primary), NI DAQ, or software test mode using pre-recorded sweep data
- **Live analysis** — baseline subtraction, polynomial and hyperfine fitting, and running polarization history plotted in real time
- **EPICS integration** — reads cryogenic temperatures, beam current, and solenoid current; writes back polarization, area, and calibration constants
- **Profile-based configuration** — a single YAML file holds a shared base and named profiles; a startup dialog lets the operator pick the session type without editing files or passing arguments

---

## Hardware Interfaces

| Subsystem | Interface | Purpose |
|---|---|---|
| FPGA DAQ | TCP/UDP | RF sweep generation, ADC readout (phase & diode) |
| NI DAQ | nidaqmx | Analog input/output alternative to FPGA |
| Rohde & Schwarz RF generator | Telnet | Center frequency and modulation control |
| LabJack | Network (LJM) | Instrument and temperature monitoring |
| IP relay | TCP | Microwave switch control |
| EPICS | pyepics | JLab slow controls — reads and writes |
| R&S shim supply | TCP | Shim coil current control |
| FM module | TCP | Frequency modulation settings |

All addresses, ports, and calibration constants are set in `pynmr_config.yaml`.

---

## Installation

```bash
git clone <repo-url>
cd jlab_pynmr
pip install -r requirements.txt
```

Key dependencies: `PySide6`, `pyqtgraph`, `numpy`, `scipy`, `lmfit`, `pyepics`, `nidaqmx`, `RsInstrument`, `labjack-ljm`, `PyYAML`.

---

## Running

```bash
conda activate pynmr312   # UNH-HOOK lab-env: UNH DAQ computer; PyNMR needs Python 3.12+ (see unh/README.md)
python pynmr_main.py
```

A startup dialog reads the available profiles from `pynmr_config.yaml` and presents them as a list. Select a profile and click OK. To bypass the dialog (e.g. for a desktop shortcut):

```bash
python pynmr_main.py -p Deuteron
python pynmr_main.py -p Proton
python pynmr_main.py -p Test          # software simulation, no hardware needed
python pynmr_main.py -c other.yaml    # use a different config file
```

---

## Configuration

Everything lives in `pynmr_config.yaml`. The file has two sections:

**Base settings** — shared defaults: DAQ parameters, EPICS PV lists, subsystem enable flags, analysis defaults, file paths.

**Profiles** — named blocks that override the base via deep merge. Channels are replaced entirely; nested settings are merged key-by-key, so a profile only needs to list what differs.

```yaml
profiles:
  Deuteron:
    channels:
      Deuteron5T:
        species: deuteron
        cent_freq: 32.7       # MHz
        mod_freq: 400.0       # kHz
        power: 400.0          # mV
        sweep_file: tri
    settings:
      default_channel: Deuteron5T
      daq_type: FPGA
      event_dir: data-d
      session_file: deuteron_session
      history_file: deuteron_history
      fpga_settings:
        ip: 129.57.161.8
      RS_settings:
        ip: 129.57.160.3
      temp_settings:
        enable: true
      analysis:
        wings: [0.01, 0.25, 0.75, 0.99]
        d_fit_params:
          wL: 32.7
          G: -0.0003
```

To switch between FPGA units, only the `fpga_settings.ip` (and optionally `RS_settings.ip`) need to change between profiles.

---

## Data Flow

### Sweep acquisition

1. The R&S generator is configured with the channel's center frequency and modulation frequency.
2. The FPGA steps through 512 frequency points. At each point it waits a configurable dwell time, then reads the phase and diode ADCs.
3. ADC values are divided by hardware calibration constants (`phase_cal`, `diode_cal`) to normalize them to a 0–1 range.
4. Sweeps are grouped into chunks (default 64). Each chunk is running-averaged into the current **Scan**.

### Event lifecycle

An **Event** is a complete polarization measurement, typically spanning hundreds of sweeps. When started:

- A new `EventData` object is created.
- EPICS values (temperatures, beam current, microwave frequency/power, shim currents) are sampled throughout.
- Chunks accumulate into `EventData.scan`.

When the sweep count is reached, analysis runs in a background thread:

1. **Baseline subtraction** — subtracts a stored background sweep from the signal sweep. Several methods are available (standard difference, polynomial, circuit model).
2. **Fitting** — fits the subtracted curve in the wing regions and extracts the area. Deuteron measurements use a full hyperfine lineshape fit (Dulya model).
3. **Polarization** — `pol = CC × area`, where CC is the user-supplied calibration constant.
4. EPICS PVs are updated with the new polarization, area, CC, and timestamp.
5. A **HistPoint** (lightweight summary) is appended to the history JSON file and shown on the polarization trend plot.
6. The full event is serialized to an event file in `event_dir`.

### Key data objects

| Object | Description |
|---|---|
| `Scan` | Running average of phase and diode arrays across all sweeps |
| `RunningScan` | Rolling N-sweep buffer used by the Tune tab |
| `EventData` | Single measurement: scan data, baseline, fit curves, polarization, EPICS snapshot |
| `Baseline` | Saved background sweep used for subtraction |
| `HistPoint` | Serializable summary of one event (pol, area, CC, timestamp, EPICS) |
| `History` | In-memory collection of all HistPoints for the current session |

---

## GUI Tabs

| Tab | Purpose |
|---|---|
| **Run** | Start/stop events, live EPICS readout, polarization history plot |
| **Tune** | Adjust RF circuit resonance; shows live phase/diode response |
| **Baseline** | Acquire and load background sweeps |
| **Analysis** | Inspect completed events; change subtraction method, fit type, and result method |
| **TE** | Thermal equilibrium measurements; fits exponential area decay |
| **Shims** | Shim coil current control *(optional)* |
| **FM** | Frequency modulation settings *(optional)* |
| **Compare** | Overlay events from different runs *(optional)* |
| **Explorer** | Browse and search the event archive *(optional)* |
| **Temp** | Chassis temperature monitor *(optional)* |
| **Magnet** | Magnetic field control *(optional)* |

Optional tabs are enabled per-profile with `enable: true` under the relevant settings key.

---

## File Layout

```
pynmr_main.py          Entry point and profile selection dialog
pynmr_config.yaml      Single unified configuration file
config/                Session state and history JSON files
data-d/                Deuteron event files (configured via event_dir)
data-p/                Proton event files
log/                   Rotating log files
te/                    TE event files
screens/               Auto-screenshots after each event
gui/                   PySide6 main window and tab modules
core/                  Data models, event bus, thread manager
hardware/              DAQ, EPICS, RF generator, instrument drivers
utils/                 Post-processing tools
```

---

## Architecture Notes

**Event bus** — a publish-subscribe system (`core/event_bus.py`) decouples the hardware threads from the GUI. Threads emit typed events (`EVENT_FINISHED`, `ANALYSIS_COMPLETED`, etc.); tabs subscribe to the events they care about.

**Thread management** — all worker threads inherit from `BaseThread` (wrapping `QThread`) and are registered with a central `ThreadManager` for orderly shutdown.

**Session persistence** — on exit, the current channel index, CC value, and tune voltages are written to `config/<session_file>.yaml` and restored on next launch for the same profile.

---

## Author

Written by J. Maxwell (https://orcid.org/0000-0003-2710-4646).

---

## References

[1] Maxwell, J. et al. "A new cw-NMR Q-meter for dynamically polarized targets for particle physics" NIM A, 1087, 171417 (2026). https://doi.org/10.1016/j.nima.2026.171417
