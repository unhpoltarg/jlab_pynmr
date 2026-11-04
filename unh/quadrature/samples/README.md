# Quadrature sample output (simulated)

These files are from one headless `TestSimQuad` session on 2026-10-27, written exactly as PyNMR writes them.
`TestSimQuad` is nmr_sim with a phase shifter shaped like the SCPHS-51+ datasheet, a 2 % gain change and a
10 mV offset change across the DAC range. Use them to update readers such as Optimizied-McClellan-Fits
`fitter/pynmr_io.py`. **They are simulated, not UNH data.**

| file | what |
|---|---|
| `2026-10-28_02-09-51__2026-10-28_02-13-13.txt` | Event file (NDJSON, one record per event). It has 18 of the session's 37 lines, kept whole and in order, so some groups are complete and some aren't |
| `quad_cal_2026-10-28_02-09-55.json` | The calibration record. PyNMR names it `<event_dir>/quad_cal/<cal_id>.json` |
| `recent_baselines.txt` | The 0° and 90° baselines set in the Baseline tab, with `quad_ref_deg` and `phase_vout` |
| `nmr_sim_truth.csv` | Simulator truth, one row per chunk, including `phase_dac_deg` and `phase_dac_v` |
| `make_samples.py` | The driver that produced the session. Run it from a scratch copy of the repo, because runs rewrite tracked files |

## What the session did
1. Set the operator tunes: Real 23.80 % (0.238) and Imag 40.76 % (0.4076).
2. **Auto Calibrate Phase:** 102 steps, then a fit.
   - Range 483°, monotonic.
   - Imag at 89.944° (truth 89.95°), gain ratio 0.9966; residual 0.032 mV, the noise level.
3. Quadrature on with `pair` (0/90), label `Baseline`: 7 events, while the simulated line sits outside the
   window. A 0° and a 90° baseline were set from them. Group `..._11-05_0001` is in the file.
4. Label `Polarize`: 21 events in pairs while the target polarizes. Groups `..._11-30_0001`, `_0009` and `_0010`
   are in the file, plus `_0011`, an unfinished pair (the run stopped after its 0° event).
5. 180° and 270° tunes set from the calibration's suggestions (0.5062, 0.5922), then sequence `cycle4`:
   9 events, all in the file (groups `..._12-42_0001` to `_0003`; the last is unfinished).

## Reading it
- Every existing field is unchanged. The `quad_*` fields are added (see `notes/quadrature_phase_design.md`).
- **Pairing:** group records by `quad_group` and order them by `quad_index`.
- **Each record's tune** is in `phase_vout`, which equals `quad_vout`.
- **Records to exclude:**
  - Only `quad_ref_deg == 0` records are polarizations.
  - The 90° and 270° records are dispersive, so their `area` and `pol` mean nothing.
  - The 180° record is the negated absorption.
- **Calibration:** `quad_cal_angle_deg` and `quad_cal_gain` give the fitted angle and gain of each tune
  relative to Real. The calibration file has the raw steps for refitting.
