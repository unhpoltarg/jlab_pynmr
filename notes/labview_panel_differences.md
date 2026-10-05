# UNH LabVIEW NMR panel vs. PyNMR: differences to consider

**Source:** a screenshot of the UNH LabVIEW NMR front panel. UNH used this custom LabVIEW system before
moving to PyNMR. The screenshot is kept on Ells's laptop at
`.claude/reference/labview_nmr_panel.png` and is deliberately not in git.

This is a working list of LabVIEW features that PyNMR lacks or does differently, recorded on 2026-10-05.
Each item will be taken up separately. Status: **now** = in progress,
**later** = not started. Readings marked *(?)* are guesses from the screenshot and need confirming.

## Sweep and window inputs
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| **Central Freq (MHz)**: live input (e.g. 32.770) | `cent_freq` per channel in `pynmr_config.yaml`; changes only by switching channel | **now**: branch `unh_dev/interactive_freq_window` |
| **Freq Span (MHz)**: live input, **full width** (0.4 gives 32.57–32.97 MHz) | `mod_freq` in kHz, a **half-width** (±), YAML only | **now**. The new PyNMR input keeps the JLab half-width (±kHz) meaning. Watch the factor of 2 when comparing to LabVIEW. |
| **# Baseline Sweeps** (e.g. 1000), separate from the sweeps per event | One `Sweeps per Event` value for everything | later |
| **# Wing Bins** (e.g. 50): wing size given as a bin count | `wings` given as four fractions (0–1) of the sweep | later |
| **dB** control next to the span (e.g. 11) *(?)*: RF level or attenuation in dB | RF `power` in mV per channel | later |

## Tuning
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| **Tune** box: Diode (V) and Phase (V) set in volts | Phase and diode DAC set from the Tune tab (sliders) | later |
| **IF Atten (dB)** | none | later |
| **Mode** toggle (Diode/Phase) | Tune tab shows both traces | later |

## Readouts and indicators
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| **IF Offset** readout (e.g. 2.6235) and **KILL IF OFFSET** button | none | later |
| **Board Temp (C)** | Chassis temp tab (LabJack, optional) | later |
| Status LEDs (e.g. next to Average, IMG/REAL) | none | later |

## Analysis and calibration controls
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| **Base / Fit / TE** pickers with **Use Base / Use Fit / Use TE** buttons on the main panel | Baseline tab, Analysis tab (method dropdowns) and TE tab are separate tabs | later |
| Fit option **Linear** | Polynomial fits of order 2, 3, 4, 6 and 8, or no fit | later |
| **Average** button with a count field | Baseline tab averages selected events | later |
| **Clear TE** | none | later |
| **Custom CC** input with **+** button; **Current CC** display | CC in the Run-tab controls (Unlock/Set), or set from the TE tab | later |
| **Area** display | Area shown on the Run tab | later (layout) |
| **Equil. Q** display *(?)*: equilibrium tensor polarization | none | later |

## Imaginary (dispersion) part
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| **Imaginary Shift** button, **Witness Imaginary Realm** button, **IMG/REAL** indicator *(?)*: show or shift the imaginary (dispersion) part of the signal | Only the phase (real) channel is analysed; the diode signal is stored but unused | later |

## Plots
| LabVIEW panel | PyNMR today | Status |
|---|---|---|
| Signal plot y-axis **Amplitude (V)** | Arbitrary units (ADC counts / calibration) | later |
| **Cursor table**: two cursors with X/Y readout on the signal plot | none | later |
| **Polarization/Area vs. Time** plot under the signal plot | Polarization history plot on the Run tab | later (compare) |
