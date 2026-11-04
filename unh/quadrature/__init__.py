"""UNH only: record both quadratures of the NMR signal by stepping the phase-detector reference.

The operator sets two Phase Tunes, Real (0 deg) and Imag (nominally 90 deg). While Quadrature is on,
the Run loop alternates events between them according to a configured sequence. A calibration
measures the actual angle and gain between the tunes. See notes/quadrature_phase_design.md and
unh/README.md. The feature is off unless unh/quadrature/quadrature.yaml enables it for the profile.

Modules:
    settings     yaml settings, with per-profile overrides
    scheduler    which tune each event uses; pairing; the record tags
    calibration  the DAC step plan, the fits, and the calibration thread
    records      event and baseline tags, calibration files
    controller   glue between PyNMR's MainWindow / tabs and the above
    ui           widgets added to the Run and Tune tabs
"""
