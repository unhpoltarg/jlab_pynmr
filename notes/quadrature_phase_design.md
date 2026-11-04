# Quadrature phase stepping: both NMR quadratures from PyNMR

Branch `unh_dev/quadrature_phase`, feature tag `quad-phase`. Code lives in `unh/quadrature/`.
It is off by default: with it off, PyNMR's behaviour and records are unchanged.

## Why

PyNMR records one projection of the Q-meter response, `phase` = Re(V·e^{-iφref}). Today the second
quadrature is rebuilt offline with a Kramers–Kronig transform, which is good to about ±2°. Separating the two
deuteron transitions needs 0.1–0.2°; each degree of phase error moves P by about 7–8 % at P ≈ 24 %. The diode
is not a second quadrature: it measures |V|, and on the 2026-10 data it tracked `phase`.

This feature alternates the phase-detector reference between two operator-set Phase Tunes, Real and Imag.
Both quadratures are then measured, one event apart.

## Hardware, from the JLab paper and the datasheet

Sources:
- J. D. Maxwell et al., "A New cw-NMR Q-meter for Dynamically Polarized Targets", arXiv:2506.14637 (2025)
- Mini-Circuits SCPHS-51+ datasheet

**The path.** The RF reference is split. One side drives the tank. The other goes through a voltage-variable
phase shifter, an attenuator and an amplifier into the LO of a Mini-Circuits ADE-1+ double-balanced mixer,
which is the phase-sensitive detector (paper §3.2.4).

**The shifter.**
- Deuteron board: SCPHS-51+, 360° at 32.7 MHz. Proton board: SPHSA-251+, 180° at 213 MHz.

**The DAC.**
- A 16-bit AD5660 on the FPGA voltage-out board drives the shifter control.
- PyNMR sends `int(phase_vout · 65535)`. The code comment gives about 16 V full scale, which is
  5 V × 3.2037 in the older scaling.

**SCPHS-51+ datasheet** (DAC fraction = V / 16 V):

| | 25 MHz | 36 MHz | 32.7 MHz (interpolated) |
|---|---|---|---|
| Phase at 15 V | 453° | 496° | about 483° |
| Slope near 0 V | about 30°/V | about 9°/V | about 15°/V |
| Steepest slope | about 55°/V (5–7 V) | about 80°/V (8–10 V) | about 65°/V |
| Insertion-loss swing | 1.30–2.43 dB | 1.16–2.37 dB | about 0.8 dB (1.26–2.03 dB) |

- The control range is 0–15 V (20 V absolute maximum). So DAC 0–0.94 covers the rated range; the Tune slider
  already allows 1.0, about 16 V.
- The phase is monotonic and strongly S-shaped.
- The control bandwidth is DC–30 kHz, so the shifter itself settles in tens of µs. The 1 ms guard is ample
  unless the voltage-out board filters the DAC.

**Mixer gain and offset.** A change in LO level changes the conversion gain and the DC offset a little. So the
calibration fits a gain change and an offset change with the DAC value.

**The paper's own suggestion** (§6): a second mixer in place of the diode chain, with a fixed 90° shift, would
give true simultaneous quadrature. This feature is the software-only route with today's box: the two
quadratures are measured one event apart instead of simultaneously.

## What the code showed

- **A Run never sends the phase DAC.** Only the Tune tab writes it, and the box holds the last value it
  latched. Each Run event opens a new connection, which sends the register with DAC channel 0 ("don't change").
- **The latch quirk:** the box takes a new DAC value only when the channel word changes from 0. On a fresh
  connection, one `set_dac(v, 1)` latches. On an open connection the write has to be `set_dac(v, 0)` and then
  `set_dac(v, 1)`.
- **Simulator:** `TestSim` already modelled the phase DAC, but as a linear, instant 180° per unit.
- **num > sweeps:** PyNMR divides each chunk by the header's sweep count. The paper (§4.3.2) says the header
  carries "how many sweeps are summed into this chunk". So the sweeps/num scaling that was seen when
  num_per_chunk > sweeps means the firmware summed `sweeps` sweeps but reported `num_per_chunk`.
  - That is inferred from code and data, and the firmware isn't documented.
  - The fix is on its own branch, `unh_dev/chunk_scaling`.

## Behaviour

### Two Phase Tunes (Tune tab)
- A "Quadrature Phase Tunes" box appears under Phase Tune Control, with Real (0°) and Imag (90°) buttons, and
  180° and 270° when the sequence uses them.
- The selected button decides which tune the existing Phase Tune spinbox edits. Selecting one sends it to the
  box through the spinbox, as any Phase Tune change does, so the operator can tune Imag by eye while Tune runs.
- Session file:
  - `phase_tune` stays the Real tune, even if the Tune tab was left on Imag.
  - `phase_tune_q` (Imag), `phase_tune_180` and `phase_tune_270` are added.
- **Auto Calibrate Phase** runs the calibration (below). **Imag from Calibration** sets Imag to the fitted 90° value.

### Acquisition (Run tab)
- A **Quadrature** checkbox and a sequence menu sit in NMR Controls. The checkbox starts unticked at every
  launch and refuses to turn on until the tunes the sequence needs are set.
- Sequences: `pair` 0/90 (the default), `abba` 0/90/90/0, `cycle4` 0/90/180/270, or a list in the yaml.
  - abba cancels a linear drift between the two quadratures; the paper's Liverpool/JLab comparison used the
    same two-and-two pattern.
  - cycle4 gives 0/180 and 90/270 pairs, which cancel the detector offset.
- Before each event, PyNMR picks the next angle. If the tune changes, it builds a new Config with
  `phase_vout` = that tune (`MainWindow.replace_config`, as the window feature does), so a Config is never
  edited in place.
- **When the DAC is written** (changed 2026-10-28 after the first hall test). Nothing is written between opening an
  event's run connection and starting its sweeps:
  - **After every event:** once its sweeps are all in, the next event's tune is written on that still-open
    connection, with the Tune tab's latch sequence (`set_dac(v, 0)` then `set_dac(v, 1)`), then `settle_ms`. The box
    is idle at that point. The next event's fresh connection leaves the DAC alone, as in any normal Run.
  - **First event of a run, or after a failed or aborted event:** one short tune-mode connection writes the tune
    first, the same way the Tune tab's `send_to_dac` does.
  - **Why:** the first version wrote the tune on the run connection just before its sweeps. That re-sent the
    register, and on the box both 640-sweep events then delivered one 64-sweep chunk and timed out. 101 one-chunk
    events were fine.
  - Each record's `quad_dac_set` says which path set its tune.
- When the run stops, the Config and the box go back to the Real tune (one `send_to_dac`, as the Tune tab does).
- With the checkbox off, a Run behaves as before. The one exception: if the Tune tab was left on Imag, the run
  first goes back to the Real tune.

### What happens to 90°/180°/270° records
- They are written to the event file and analysed like every other record. Their `area` and `pol` are not
  polarizations.
- They are not written to EPICS and get no history point, so the pol plot and the TE tab see only Real records.
- The data streamer skips them.
- The Run tab's big pol number keeps showing the last Real record.

### Baselines
- In the Baseline tab, selected rows that carry `quad_ref_deg` are averaged separately for each angle.
- The 0° average becomes the main baseline, and the other angles are kept for events at those angles.
- Every angle's baseline goes into `recent_baselines.txt`, with `quad_ref_deg` and `phase_vout`.
- An event whose angle has no baseline uses the main baseline, and `quad_base_ref_deg` records which angle's
  baseline was actually subtracted (null for an untagged one).

### Calibration
The calibration runs only while Run and Tune are stopped. It uses one tune-mode connection, the Tune latch
sequence for every DAC change, and `tune_per_chunk` chunks, the same box usage as a Tune session.

1. **Step plan:**
   - start at the Real tune;
   - step the grid from `v_min` to `v_max` (41 points, 0–0.94), then back down;
   - include the operator's other tunes as steps of their own, so their angles are measured, not interpolated;
   - return to the Real tune every 5 steps to track drift;
   - finish at the Real tune.

   Each step averages `sweeps_per_step` (128) sweeps. With the defaults that is about 105 steps, a few minutes.
2. **Settle test** (diagnostic only): jump from v_min to v_max, then record back-to-back chunks. The result
   is recorded; `settle_ms` is never changed automatically.
3. **Fit.** Variable projection on the phase sweeps, averaged into 32 frequency bins:

   y_kj = g(v_k)·(1 + drift·τ_k)·[Re W_j cos φ_k + Im W_j sin φ_k] + offset(v_k)

   - φ is free at every distinct DAC value. There is no assumed shape, because the shifter is S-shaped.
   - g and the offset are low-order polynomials in v (`gain_order` 2, `offset_order` 1).
   - W_j, the complex response in each bin at the Real tune (Q-curve plus any line), is solved linearly.
4. **Outputs:**
   - the angle and gain ratio of each tune relative to Real, with errors;
   - the φ table and its range, and whether it is monotonic;
   - the suggested DAC values for ±90/180/270°;
   - the residual rms.

   The DAC is put back on the tune the Tune tab shows.

**Limits of the calibration.** These are worth knowing before trusting a number to 0.1°:
- **The rotation sign is not observable** from projections: φ → −φ with W → W\* gives identical data. φ is
  reported increasing with v.
- **Projections fix the reference direction only up to a 2×2 linear map.**
  - Antiparallel settings (0°/180°) are free of this. A 90° angle needs a "metric" assumption, which here is
    that the gain is a smooth low-order polynomial in v.
  - In simulation with the SCPHS-51+ curve:
    - a constant gain gives the 90° angle to 0.001°;
    - a linear gain is exact;
    - a gain following half of the datasheet insertion-loss bumps gives errors of 0.16–0.66°, depending on
      `gain_order`.
  - The fit residual shows that mismatch: 0.7–2.3 mV against 0.03 mV of noise.
  - **So the PyNMR calibration is for choosing and monitoring the Imag tune (sub-degree).** The 0.1° number
    should come from the offline complex lineshape fit, with δ and the gain ratio free. That fit uses the
    Kramers–Kronig relation between χ′ and χ″ and also fixes the sign. The raw calibration steps are saved, so
    the calibration can be refit offline with other assumptions.

### Reconstructing quadratures offline
- Model: P_θ = g_θ·Re(V e^{-iθ}) + o_θ.
- With 0° and an Imag tune at a known angle δ and gain ratio g:
  - I = P_0 − o_0
  - Q = ((P_δ − o_δ)/g − I cos δ) / sin δ
- The noise penalty is 1/sin δ, so δ need not be exactly 90°.
- With cycle4, (P_0 − P_180)/2 and (P_90 − P_270)/2 remove the offsets.

## Settings: `unh/quadrature/quadrature.yaml`

| key | default | meaning |
|---|---|---|
| `enable` | False | adds the controls; `profiles: {TestSimQuad: {enable: True}}` |
| `sequence` | pair | pair, abba, cycle4, or a list of angles that includes 0 |
| `settle_ms` | 1 | wait after each Run DAC write (the original 1 ms guard, Ells 2026-10-27) |
| `cal.v_min`, `cal.v_max` | 0, 0.94 | range stepped; 0.94 × 16 V = 15 V, the SCPHS-51+ rated top |
| `cal.steps`, `cal.passes` | 41, 2 | grid points per pass; up then down |
| `cal.sweeps_per_step` | 128 | rounded up to a multiple of `tune_per_chunk` |
| `cal.ref_every` | 5 | back to the Real tune every N steps |
| `cal.settle_ms` | 1 | wait after each calibration step |
| `cal.settle_test_chunks` | 8 | 0 skips the settle test |
| `cal.gain_order`, `cal.offset_order` | 2, 1 | fit polynomial orders |
| `cal.fit_drift`, `cal.bins` | True, 32 | |
| `cal.out_dir` | quad_cal | `<event_dir>/quad_cal/<cal_id>.json` |

## Record schema

### Event records (one per event, as now)
Nothing changes when quadrature is off. While it is on, these top-level keys are added, all plain JSON:

| key | meaning |
|---|---|
| `phase_vout` | existing key: the Phase Tune **used for this record** (Real or Imag) |
| `quad_mode` | `pair` / `abba` / `cycle4` / `custom` |
| `quad_sequence` | e.g. `[0, 90]` |
| `quad_state` | `ok`, or `suspended` (the box refused a DAC write, and the rest of the run is Real only) |
| `quad_ref_deg` | nominal angle: 0, 90, 180 or 270 |
| `quad_vout` | DAC value written for this record (= `phase_vout`) |
| `quad_tunes` | `{"0": vReal, "90": vImag, ...}` |
| `quad_group` | `<run start UTC>_<n>`, one pass through the sequence (a pair or a cycle) |
| `quad_index` | position in the group |
| `quad_settle_ms` | wait used |
| `quad_dac_ok` | the box accepted the write that set this record's tune |
| `quad_dac_set` | how the tune was set: `end of previous event`, or `before the event (Tune-style connection)` |
| `quad_cal_id` | calibration in force, or null |
| `quad_cal_angle_deg`, `quad_cal_gain` | fitted angle and gain of this tune relative to Real |
| `quad_cal_valid` | that calibration was taken with these tunes and covers this value |
| `quad_base_ref_deg` | angle of the baseline subtracted (null = an untagged baseline) |

`label` is untouched.

**Why one record per event, not a combined I+Q record:**
- Every consumer assumes one `phase` array per record: the Baseline, TE and SuperTE tabs, the explorer, the
  combiner, the streamer, EPICS and history.
- The two quadratures are taken at different times anyway.
- A reader pairs records by `quad_group` and gets both stamps for free.

### Calibration records
Calibration records are separate files, so event-file readers are unaffected:
`<event_dir>/quad_cal/<cal_id>.json`, one JSON object each. Fields:
- `record_type: "quad_calibration"`, `schema: 1`, `cal_id`, start and stop time and stamp
- `profile`, `daq_type`, `channel`, `species`, `cent_freq`, `mod_freq`, `freq_list`, `diode_vout`
- `tunes`, `restore_vout`, `settings`, `settle_ms`, `sweeps_per_step`, `tune_per_chunk`, `pynmr_git`
- `steps`: `[{order, vout, pass, kind (ref/grid/tune), t_s, stamp, dac_ok, num, phase[], diode[]}]`
- `settle_test`, `status`, `error`
- `fit`: as `unh/quadrature/calfit.py:fit_calibration` returns it (φ table with errors, tunes, suggestions,
  gain and offset coefficients, W, residual, notes)

A sample from the simulator is in `unh/quadrature/samples/`.

## Failure modes

| what | what PyNMR does |
|---|---|
| Box refuses a DAC write | `quad_dac_ok=false`; quadrature is suspended for the rest of the run (Real tune); status bar and log |
| Tunes, channel or window change after the calibration | `quad_cal_valid=false`; the Run tab says "no current calibration"; data stays usable |
| PyNMR dies on the Imag tune | The box stays on Imag. The next start restores the Real tune from the session (if nonzero), and the first quadrature event writes the DAC anyway |
| Stop during an Imag event | The record is tagged normally; `finish_run` restores the Real tune |
| No baseline for an angle | Main baseline used; `quad_base_ref_deg` says so |
| Calibration error or timeout | Stop-sweep sent, DAC restored, partial record saved with `status: error` |
| FitDeuteron on dispersive records | Can be slow (about 25 s with eta > 0); records are analysed like any other |
| NIDAQ | No phase DAC: the checkbox and Calibrate are disabled |

## Questions still open (not blockers)
- Does the voltage-out board filter the DAC (which would set the real settling)? Is the full scale 16 V?
- Does the mixer LO run in saturation (which would decide how much of the 0.8 dB insertion-loss swing becomes gain)?
- Does DAC channel 0 truly leave the DAC untouched? PyNMR has always relied on that.
- What did LabVIEW's IMG/REAL control do (`notes/labview_panel_differences.md`)?
- Auto-phase (nudging the Real tune to stay absorptive) is not built. If it ever is, it must be logged per
  record and be off by default.

## Hardware use
- Develop and test in TestSimQuad now. Use on the box only after `unh_dev/daq_connection` (clean close,
  stop-after-error) is merged into `unh`.
- First hardware session: run one calibration with the target warm or at TE. Check `range_deg`, `monotonic`,
  the residual and the settle test, then take a few pairs.
