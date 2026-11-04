"""Quadrature widgets, added to the existing Run and Tune tabs when the feature is enabled.

Tune tab, below Phase Tune Control: a Real / Imag (/ 180 / 270) selector that switches which tune the
Phase Tune spinbox edits, plus Auto Tune, Auto Calibrate Phase, Stop and "Imag from calibration" buttons and a result line.
Run tab, in NMR Controls: a Quadrature checkbox, the sequence, and a status line. While Quadrature is on,
a grid of plots (QuadPlots) replaces JLab's three: each stage split into Real (0°) and Imag (90°).

The widgets only listen to the tabs' existing signals (the Phase Tune spinbox and the Run buttons), so the
tab code itself is unchanged.
"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QPushButton, QRadioButton, QVBoxLayout, QWidget)

from . import records
from .controller import summary_line
from .settings import SEQUENCES, sequence_name

ANGLE_NAMES = {0: 'Real (0°)', 90: 'Imag (90°)', 180: '180°', 270: '270°'}


class QuadPlots:
    """Run-tab plots while Quadrature is on: a grid in place of JLab's three plots.

    Columns are the processing stages (Raw Signal, Baseline Subtracted, Fit Subtracted); the top row is Real (0°)
    and the bottom row Imag (90°). In cycle4, -1 x the 180° record is drawn over each 0° plot and -1 x the 270°
    record over each 90° plot. A raw curve follows its event live while the sweeps come in; every other curve
    changes when a record at its own angle finishes. Turning Quadrature off shows JLab's three plots again.
    On the Raw row the overlays sit apart from 0°/90° by twice any detector DC offset; that gap is the offset.
    """
    PLOT_HEIGHT = 50
    STAGES = (('raw', 'Raw Signal'), ('sub', 'Baseline Subtracted'), ('fin', 'Fit Subtracted'))
    ROWS = ((0, 180, 'Real (0°)'), (90, 270, 'Imag (90°)'))
    OVERLAY_PEN = dict(color=(255, 140, 0), width=1.5)

    def __init__(self, tab):
        self.tab = tab
        self.on = False
        self.overlays = False
        self.grid = QWidget()
        g = QGridLayout(self.grid)
        g.setContentsMargins(0, 0, 0, 0)
        pens = {'raw': tab.raw_pen, 'sub': tab.sub_pen, 'fin': tab.fin_pen}
        overlay = pg.mkPen(**self.OVERLAY_PEN)
        self.wids, self.legends, self.curves, self.extra = {}, {}, {}, {}
        for col, (stage, name) in enumerate(self.STAGES):
            for row, (angle, opposite, label) in enumerate(self.ROWS):
                w = pg.PlotWidget(title=f'{name}: {label}')
                w.showGrid(True, True, alpha=0.2)
                w.setMouseEnabled(x=False, y=False)
                w.setMinimumHeight(self.PLOT_HEIGHT)
                g.addWidget(w, row, col)
                self.wids[(stage, angle)] = w
                self.legends[(stage, angle)] = w.addLegend(offset=(5, 5))
                self.curves[(stage, angle)] = w.plot([], [], pen=pens[stage])
                self.curves[(stage, opposite)] = w.plot([], [], pen=overlay)    # drawn as -1 x that record
                self.curves[(stage, opposite)].setVisible(False)
        self.extra['fitcurve', 0] = self.wids[('sub', 0)].plot([], [], pen=tab.fit_pen)    # as JLab's sub plot
        self.extra['fitcurve', 90] = self.wids[('sub', 90)].plot([], [], pen=tab.fit_pen)
        self.extra['rescurve', 0] = self.wids[('fin', 0)].plot([], [], pen=tab.res_pen)    # the 0° fit result
        self.extra['quad_kk_curve', 90] = self.wids[('fin', 90)].plot(       # KK of the 0° absorption, fitted scale
            [], [], pen=pg.mkPen(tab.res_pen.color(), width=2, style=pg.QtCore.Qt.DashLine))
        self.grid.hide()
        tab.lowerlayout.addWidget(self.grid, 1)
        self.last_events = {}                                   # angle -> latest finished record
        jlab_update = tab.update_run_plot                       # JLab's live raw-plot update, called per chunk
        def update_run_plot(*args, **kwargs):
            jlab_update(*args, **kwargs)
            self.show_live()
        tab.update_run_plot = update_run_plot

    def set_mode(self, on, sequence):
        """Show the grid for Quadrature on (JLab's plots for off), and the 180°/270° overlays if the sequence has them."""
        on = bool(on)
        if on != self.on:
            for w in (self.tab.raw_wid, self.tab.sub_wid, self.tab.fin_wid):
                w.setVisible(not on)
            if on:
                for c in list(self.curves.values()) + list(self.extra.values()):
                    c.setData([], [])
            self.grid.setVisible(on)
            self.on = on
        overlays = on and bool({180, 270} & set(sequence))
        if overlays != self.overlays:
            self.overlays = overlays
            for stage, _ in self.STAGES:
                for angle, opposite, _ in self.ROWS:
                    main, over = self.curves[(stage, angle)], self.curves[(stage, opposite)]
                    over.setVisible(overlays)
                    legend = self.legends[(stage, angle)]
                    legend.removeItem(main)
                    legend.removeItem(over)
                    if overlays:
                        legend.addItem(main, f'{angle}°')
                        legend.addItem(over, f'-1 × {opposite}°')

    @staticmethod
    def _xy(event, attr):
        try:
            x = np.asarray(event.scan.freq_list, dtype=float)
            y = np.asarray(getattr(event, attr) if attr != 'phase' else event.scan.phase, dtype=float)
        except (AttributeError, TypeError, ValueError):
            return None, None
        if len(x) == 0 or len(x) != len(y):
            return None, None
        return x, y

    def _put(self, stage, angle, event, attr):
        x, y = self._xy(event, attr)
        if x is not None:
            self.curves[(stage, angle)].setData(x, -y if angle in (180, 270) else y)

    def show_live(self):
        """During an event: its raw curve follows the sweeps as they come in."""
        event = getattr(self.tab.parent, 'event', None)
        if not self.on or getattr(event, 'quad_ref_deg', None) is None:
            return
        angle = records.angle_of(event)
        if ('raw', angle) in self.curves:
            self._put('raw', angle, event, 'phase')

    def show_event(self, event):
        """Draw a finished quadrature record on its angle's curves; other angles' curves are left alone."""
        if not self.on or getattr(event, 'quad_ref_deg', None) is None:
            return
        angle = records.angle_of(event)
        if ('raw', angle) not in self.curves:
            return
        self.last_events[angle] = event
        self._put('raw', angle, event, 'phase')
        self._put('sub', angle, event, 'basesub')
        self._put('fin', angle, event, 'fitsub')
        for name, stage_angle in (('fitcurve', angle), ('rescurve', angle), ('quad_kk_curve', angle)):
            item = self.extra.get((name, stage_angle))
            if item is not None:
                x, y = self._xy(event, name)
                item.setData(*(([], []) if x is None else (x, y)))
        wp = getattr(self.tab, 'wing_points', None)            # unh/wing_points.py: mark the fitted points
        if wp is not None:
            wp.draw_quad(event)


class BasePlots:
    """Baseline tab plots while quadrature is in use: a 2 x 2 grid in place of JLab's two plots.

    Left column absorptive (0°, with -1 x 180° over it), right column dispersive (90°, with -1 x 270°). Top row
    Selected Baseline, bottom row Current Sweep minus Baseline, using the latest sweep at each angle.
    """
    ROWS = (('base', 'Selected Baseline'), ('sub', 'Current Sweep minus Baseline'))
    COLS = ((0, 180, 'Absorptive (0°)'), (90, 270, 'Dispersive (90°)'))
    OVERLAY_PEN = dict(color=(255, 140, 0), width=1.5)

    def __init__(self, bt):
        self.bt = bt
        self.on = False
        self.grid = QWidget()
        g = QGridLayout(self.grid)
        g.setContentsMargins(0, 0, 0, 0)
        pens = {'base': bt.sel_pen, 'sub': bt.sub_pen}
        overlay = pg.mkPen(**self.OVERLAY_PEN)
        self.wids, self.legends, self.curves = {}, {}, {}
        for row, (stage, name) in enumerate(self.ROWS):
            for col, (angle, opposite, label) in enumerate(self.COLS):
                w = pg.PlotWidget(title=f'{name}: {label}')
                w.showGrid(True, True)
                g.addWidget(w, row, col)
                self.wids[(stage, angle)] = w
                self.legends[(stage, angle)] = w.addLegend(offset=(5, 5))
                self.curves[(stage, angle)] = w.plot([], [], pen=pens[stage])
                self.curves[(stage, opposite)] = w.plot([], [], pen=overlay)     # drawn as -1 x that angle
        self.grid.hide()
        bt.right.addWidget(self.grid, 1)

    def set_visible(self, on):
        on = bool(on)
        if on != self.on:
            self.bt.base_wid.setVisible(not on)
            self.bt.sub_wid.setVisible(not on)
            self.grid.setVisible(on)
            self.on = on

    def update(self, bases, latest):
        """bases, latest: {angle: (freqs, phase)} for the baselines and the latest sweep at each angle."""
        for (stage, angle), curve in self.curves.items():
            sign = -1.0 if angle in (180, 270) else 1.0
            b = bases.get(angle)
            if stage == 'base':
                curve.setData(*((b[0], sign * np.asarray(b[1], dtype=float)) if b is not None else ([], [])))
                continue
            s = latest.get(angle)
            if b is None or s is None or len(b[1]) != len(s[1]):
                curve.setData([], [])
            else:
                curve.setData(s[0], sign * (np.asarray(s[1], dtype=float) - np.asarray(b[1], dtype=float)))
        for stage, _ in self.ROWS:
            for angle, opposite, _ in self.COLS:
                legend = self.legends[(stage, angle)]
                legend.clear()
                main, over = self.curves[(stage, angle)], self.curves[(stage, opposite)]
                if over.getData()[1] is not None and len(over.getData()[1]):
                    legend.addItem(main, f'{angle}°')
                    legend.addItem(over, f'-1 × {opposite}°')


class QuadUI:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        mw = ctrl.mw
        tune, run = mw.tune_tab, mw.run_tab

        # Tune tab: a short full-width strip under both tune plots, so the diode and phase plots keep equal size
        self.tune_box = QGroupBox('Quadrature Phase Tunes')
        self.tune_box.setLayout(QHBoxLayout())
        self.tune_box.setMaximumHeight(480)          # room for a taller Auto Tune / calibration plot
        controls = QVBoxLayout()
        self.tune_box.layout().addLayout(controls, 1)
        row = QHBoxLayout()
        self.radio_group = QButtonGroup(self.tune_box)
        self.radios, self.values = {}, {}
        for angle, name in ANGLE_NAMES.items():
            r = QRadioButton(name)
            self.radio_group.addButton(r, angle)
            self.radios[angle] = r
            self.values[angle] = QLabel('')
            row.addWidget(r)
            row.addWidget(self.values[angle])
        self.radios[0].setChecked(True)
        self.radio_group.idClicked.connect(ctrl.select_tune)
        controls.addLayout(row)
        buttons = QHBoxLayout()
        self.cal_button = QPushButton('Auto Calibrate Phase')
        self.cal_button.clicked.connect(ctrl.start_calibration)
        self.stop_button = QPushButton('Stop Calibration')
        self.stop_button.clicked.connect(ctrl.stop_calibration)
        self.suggest_button = QPushButton('Imag from Calibration')
        self.suggest_button.setToolTip('Set the Imag tune to the DAC value the last calibration found for 90°')
        self.suggest_button.clicked.connect(lambda: ctrl.use_suggested(90))
        self.auto_button = QPushButton('Auto Tune')
        self.auto_button.setToolTip('Set each tune roughly by hand first. Auto Tune then steps the phase DAC around '
                                    'them and moves them to the true 0/90/180/270 deg: 0 deg is the absorptive '
                                    'direction at the centre frequency, found from the Q-curve. About 50 s for '
                                    'Real/Imag. The Tune loop pauses while it runs.')
        self.auto_button.clicked.connect(ctrl.start_autotune)
        self.undo_button = QPushButton('Undo Auto Tune')
        self.undo_button.setToolTip('Put back the tunes the last Auto Tune started from')
        self.undo_button.clicked.connect(ctrl.undo_autotune)
        self.stop_button.setText('Stop')
        self.stop_button.setToolTip('Stop the calibration or Auto Tune after the current step')
        for b in (self.auto_button, self.undo_button, self.cal_button, self.stop_button, self.suggest_button):
            buttons.addWidget(b)
        controls.addLayout(buttons)
        self.cal_label = QLabel('No phase calibration yet.')
        self.cal_label.setWordWrap(True)
        controls.addWidget(self.cal_label)
        self.trace_plot = pg.PlotWidget(title='Auto Tune: Q-curve trace in the true 0°/90° frame '
                                              '(axes scaled separately)')
        self.trace_plot.showGrid(True, True)
        self.trace_plot.setLabel('bottom', 'Absorptive, 0° (mV)')
        self.trace_plot.setLabel('left', 'Dispersive, 90° (mV)')
        self.trace_plot.hide()
        controls.addWidget(self.trace_plot, 100)     # all the open space when shown
        controls.addStretch(1)                       # keeps the controls at the top while it is hidden
        # live view of the calibration: mean phase and diode output vs phase DAC (%)
        self.cal_plot = pg.PlotWidget(title='Calibration: mean output vs Phase DAC (%)')
        self.cal_plot.showGrid(True, True)
        self.cal_plot.addLegend(offset=(5, 5))
        self.cal_phase = self.cal_plot.plot([], [], pen=None, symbol='o', symbolSize=5, symbolBrush=(0, 0, 204),
                                            name='phase')
        self.cal_diode = self.cal_plot.plot([], [], pen=None, symbol='t', symbolSize=5, symbolBrush=(250, 0, 0),
                                            name='diode')
        self.cal_plot.setMinimumHeight(400)          # about 2.5x the original strip's plot
        self.cal_plot.setLabel('bottom', 'Phase DAC (%)')
        self.cal_plot.setLabel('left', 'Mean output (V)')
        self.tune_box.layout().addWidget(self.cal_plot, 1)
        self.cal_points = []
        self.trace_items = []
        tune.main.addWidget(self.tune_box)
        tune.phase_spin.valueChanged.connect(ctrl.tune_spin_changed)   # after JLab's own slot

        # Run tab
        self.check = QCheckBox('Quadrature')
        self.check.setToolTip('Alternate events between the Phase Tunes set on the Tune tab')
        self.check.toggled.connect(self.check_toggled)
        self.seq_combo = QComboBox()
        self.sequences = dict(SEQUENCES)
        own = list(ctrl.sched.sequence)
        if sequence_name(own) == 'custom':
            self.sequences['custom'] = own
        for name, seq in self.sequences.items():
            self.seq_combo.addItem(f"{name}: {'/'.join(str(a) for a in seq)}", name)
        self.seq_combo.setCurrentIndex(list(self.sequences).index(sequence_name(own)))
        self.seq_combo.currentIndexChanged.connect(self.seq_changed)
        grid = run.controls_box.layout()
        r = grid.rowCount()
        grid.addWidget(self.check, r, 0)
        grid.addWidget(self.seq_combo, r, 1)
        self.run_label = QLabel('')
        self.run_label.setWordWrap(True)
        grid.addWidget(self.run_label, r + 1, 0, 1, 2)
        self.base_label = QLabel('')
        self.base_label.setWordWrap(True)
        grid.addWidget(self.base_label, r + 2, 0, 1, 2)
        self.plots = QuadPlots(run)

        # Baseline tab: a per-angle summary of the selection above Set Baseline, and each angle's average plotted
        bt = getattr(mw, 'base_tab', None)
        self.base_tab = bt
        if bt is not None:
            self.base_sel = QLabel('')
            self.base_sel.setWordWrap(True)
            lay = bt.base_box.layout()
            lay.insertWidget(lay.indexOf(bt.base_but), self.base_sel)
            self.base_plots = BasePlots(bt)

        run.run_button.toggled.connect(lambda _: self.refresh())
        tune.run_button.toggled.connect(lambda _: self.refresh())
        if ctrl.sched.calibration:
            self.show_calibration(ctrl.sched.calibration)
        self.refresh()

    # -- slots -----------------------------------------------------------------
    def check_toggled(self, on):
        actual = self.ctrl.set_active(on)
        if actual != on:
            self.check.blockSignals(True)
            self.check.setChecked(actual)
            self.check.blockSignals(False)
        self.refresh()

    def seq_changed(self, i):
        self.ctrl.set_sequence(self.sequences[self.seq_combo.itemData(i)])
        if self.ctrl.sched.active and self.ctrl.sched.missing_tunes():
            self.check.setChecked(False)
        self.refresh()

    def _scan_view(self, title):
        """Clear the mean-output-vs-DAC plot for a new scan, and hide the last Auto Tune trace."""
        self.trace_plot.clear()
        self.trace_items = []
        self.trace_plot.hide()
        self.cal_plot.setAspectLocked(False)
        self.cal_plot.setTitle(title)
        self.cal_plot.setLabel('bottom', 'Phase DAC (%)')
        self.cal_plot.setLabel('left', 'Mean output (V)')
        self.cal_phase.setVisible(True)
        self.cal_diode.setVisible(True)
        if self.cal_plot.plotItem.legend is not None:
            self.cal_plot.plotItem.legend.setVisible(True)
        self.cal_points = []
        self.cal_phase.setData([], [])
        self.cal_diode.setData([], [])
        self.cal_plot.enableAutoRange()

    def cal_started(self):
        self._scan_view('Calibration: mean output vs Phase DAC (%)')
        self.cal_label.setText('Calibrating: connecting...')

    def autotune_started(self):
        self._scan_view('Auto Tune: mean output vs Phase DAC (%)')
        self.cal_label.setText('Auto Tune: connecting...')

    def cal_progress(self, data, what='Calibrating'):
        step, of, vout, t = data['step'], data['of'], data['vout'], data.get('t_s', 0.0)
        left = t / step * (of - step) if step else 0.0
        if what == 'Calibrating':
            timing = f"{t:.0f} s elapsed, about {left:.0f} s left. Don't close PyNMR until it says done."
        else:
            timing = f'{t:.0f} s elapsed.'
        self.cal_label.setText(f'{what}: step {step} of {of} (phase DAC {vout * 100:.2f} %), {timing}')
        tune = self.ctrl.mw.tune_tab                     # the step's sweep on the Diode and Phase Signal plots
        freqs = np.asarray(self.ctrl.mw.config.freq_list, dtype=float)
        for key, plot in (('diode', tune.diode_plot), ('phase', tune.phase_plot)):
            y = data.get(key)
            if y is not None and len(y) == len(freqs):
                plot.setData(freqs, np.asarray(y, dtype=float))
        if data.get('mean_phase') is not None:
            self.cal_points.append((vout * 100, data['mean_phase'], data.get('mean_diode')))
            x = [p[0] for p in self.cal_points]
            self.cal_phase.setData(x, [p[1] for p in self.cal_points])
            if all(p[2] is not None for p in self.cal_points):
                self.cal_diode.setData(x, [p[2] for p in self.cal_points])

    def show_autotune(self, rec, text):
        """Auto Tune result: the summary line, and the Q-curve trace with the absorptive direction."""
        self.cal_label.setText(text)
        last = (rec.get('passes') or [{}])[-1].get('analysis') or {}
        trace = last.get('trace') or {}
        if 'W_re_V' not in trace:
            self.refresh()
            return
        W = np.asarray(trace['W_re_V']) + 1j * np.asarray(trace['W_im_V'])
        c = complex(*trace['ref_point_V']) if trace.get('success') else W.mean()
        d = (W - c) * 1e3                        # relative to the trace at the centre frequency, mV
        tp = self.trace_plot
        tp.clear()
        # rotate into the frame Auto Tune found: x along the absorptive (0 deg) direction, y along 90 deg. Each axis
        # is scaled to its own data, so the trace's bow shows; the two directions are the axes themselves.
        rot = np.exp(-1j * np.radians(trace['theta_ref_deg'])) if trace.get('success') else 1.0
        dr = d * rot
        items = [tp.plot(dr.real, dr.imag, pen=None, symbol='o', symbolSize=5, symbolBrush=(0, 0, 204))]
        if trace.get('success'):
            cv = np.asarray(trace['curve_V'], dtype=float)
            w = ((cv[:, 0] + 1j * cv[:, 1]) - c) * 1e3 * rot
            items.append(tp.plot(w.real, w.imag, pen=pg.mkPen((0, 160, 0), width=1.5)))
            for angle, colour in ((0, (250, 0, 0)), (90, (255, 140, 0))):   # 0 deg (absorptive) and 90 deg axes
                line = pg.InfiniteLine(pos=0, angle=angle, pen=pg.mkPen(colour, width=1.5, style=pg.QtCore.Qt.DashLine))
                tp.addItem(line)
                items.append(line)
        self.trace_items = items
        tp.show()
        tp.enableAutoRange()
        self.refresh()

    # -- Baseline tab ------------------------------------------------------------
    BASE_COLS = ['Angle', 'Phase DAC (%)']

    def base_table(self, bt):
        """BaseTab.open_basefile: add Angle and Phase DAC columns after JLab's eight."""
        from PySide6.QtGui import QStandardItem
        model = bt.event_model
        n = 8
        for k, name in enumerate(self.BASE_COLS):
            model.setHorizontalHeaderItem(n + k, QStandardItem(name))
        for i in range(model.rowCount()):
            row = bt.events.get(model.data(model.index(i, 0)), {})
            angle = f"{row['quad_ref_deg']}°" if row.get('quad_ref_deg') is not None else '—'
            v = row.get('phase_vout')
            model.setItem(i, n, QStandardItem(angle))
            model.setItem(i, n + 1, QStandardItem('' if v is None else f'{float(v) * 100:.2f}'))
        header = bt.event_table.horizontalHeader()       # show them right after Time, where they stay in view
        for k in range(len(self.BASE_COLS)):
            if header.visualIndex(n + k) != 3 + k:
                header.moveSection(header.visualIndex(n + k), 3 + k)
        bt.event_table.resizeColumnsToContents()

    def base_selected(self, bt):
        """BaseTab.select_event: say what Set Baseline will do for each angle, and plot each angle's average."""
        c = self.ctrl
        bases = getattr(bt, 'quad_bases', None) or {}
        self.base_refresh()
        if not bases:
            self.base_sel.setText('Selection has no quadrature rows: it will be the one baseline for every angle.'
                                  if getattr(bt, 'base_stamps', None) else '')
            return
        parts, problems = [], []
        for a in sorted(bases):
            d = bases[a]
            v = d.get('phase_vout')
            parts.append(f"{a}°: {len(d['base_stamps'])} rows, {d['sweeps']} sweeps"
                         + ('' if v is None else f", DAC {float(v) * 100:.2f} %"))
            if d.get('dropped_stamps'):
                problems.append(f"{a}°: {len(d['dropped_stamps'])} rows at another tune left out")
            tune = c.sched.tunes.get(a)
            if v is not None and tune is not None and not records.same_vout(v, tune):
                problems.append(f"{a}° taken at DAC {float(v) * 100:.2f} %, the tune is now {tune * 100:.2f} %")
        missing = sorted(set(c.sched.sequence) - set(bases))
        if missing:
            problems.append('no rows for ' + ', '.join(f'{a}°' for a in missing) + ' (those events would use 0°)')
        text = 'Set Baseline will set one baseline per angle. ' + '; '.join(parts) + '.'
        if problems:
            text += '<br><span style="color:#d00000">' + '; '.join(problems) + '.</span>'
        self.base_sel.setText(text)

    def base_refresh(self):
        """Baseline tab grid: the selection if it has quadrature rows, else the baselines in use; shown while
        Quadrature is ticked or a quadrature selection is up."""
        bt = getattr(self, 'base_tab', None)
        if bt is None:
            return
        sel = getattr(bt, 'quad_bases', None) or {}
        if sel:
            bases = {a: (d['freq_list'], d['phase']) for a, d in sel.items()}
        else:
            bases = {a: (getattr(b, 'freq_list', None), b.phase) for a, b in self.ctrl.baselines.items()
                     if getattr(b, 'freq_list', None) is not None}
        self.base_plots.set_visible(self.ctrl.sched.active or bool(sel))
        if self.base_plots.on:
            self.base_plots.update(bases, getattr(self.ctrl, 'latest_raw', {}))

    def baseline_line(self):
        """Run tab: one line with each angle's baseline state, red if any needs attention."""
        st = self.ctrl.baseline_status()
        words = {'ok': 'ok', 'none': 'none (uses 0°)', 'other tune': 'taken at another tune',
                 'not set': 'not set', 'untagged': 'untagged'}
        text = 'Baselines: ' + ', '.join(f'{a}° {words[s]}' for a, s in st) + '.'
        if any(s != 'ok' for _, s in st):
            return f'<span style="color:#d00000">{text} Take or select baselines on the Baseline tab.</span>'
        return text

    def show_calibration(self, rec):
        self.cal_label.setText(summary_line(rec))
        self.refresh()

    def show_selected_quietly(self):
        """Show the selected tune on the Phase Tune controls without sending it to the box."""
        tune = self.ctrl.mw.tune_tab
        v = self.ctrl.sched.tunes.get(self.ctrl.selected)
        self.radios[self.ctrl.selected].setChecked(True)
        if v is None:
            return
        for w, value in ((tune.phase_spin, v * 100), (tune.phase_slider, int(v * 1000))):
            w.blockSignals(True)
            w.setValue(value)
            w.blockSignals(False)

    # -- state -----------------------------------------------------------------
    def refresh(self):
        c = self.ctrl
        mw = c.mw
        running = mw.run_in_progress() if hasattr(mw, 'run_tab') else False
        tuning = mw.tune_tab.run_button.isChecked()
        cal = c.calibrating()
        needed = set(c.sched.sequence) | {0, 90}
        for angle, radio in self.radios.items():
            radio.setVisible(angle in needed)
            self.values[angle].setVisible(angle in needed)
            radio.setEnabled(not running and not cal)
            v = c.sched.tunes.get(angle)
            self.values[angle].setText('not set' if v is None else f'DAC {v * 100:.2f} %')
        self.check.setEnabled(c.fpga and not running and not cal)
        self.seq_combo.setEnabled(not running and not cal)
        self.cal_button.setEnabled(c.fpga and not running and not tuning and not cal)
        self.stop_button.setEnabled(cal)
        self.auto_button.setEnabled(c.fpga and not running and not cal)
        self.undo_button.setEnabled(bool(getattr(c, '_autotune_undo', None)) and not running and not cal)
        fit = (c.sched.calibration or {}).get('fit') or {}
        self.suggest_button.setEnabled(bool(fit.get('success')) and not running and not cal)
        self.plots.set_mode(c.sched.active, c.sched.sequence)
        self.base_label.setText(self.baseline_line() if c.sched.active else '')
        self.base_refresh()
        if not c.sched.active:
            why = getattr(c, 'refusal', None)
            if why:
                self.run_label.setText(f'<span style="color:#d00000">Quadrature not turned on: {why}.</span>')
            else:
                self.run_label.setText('Quadrature off.')
        else:
            tunes = ', '.join(f"{ANGLE_NAMES[a].split(' ')[0]} at DAC {c.sched.tunes[a] * 100:.2f} %"
                              for a in sorted(set(c.sched.sequence)))
            c.update_context()
            if c.sched.calibration_valid():
                cal_text = f"calibration {c.sched.calibration['cal_id']}"
            else:
                cal_text = 'no current calibration'
            state = f' SUSPENDED: {c.sched.suspended}.' if c.sched.suspended else ''
            self.run_label.setText(f"Quadrature on ({'/'.join(str(a) for a in c.sched.sequence)}): {tunes}; "
                                   f"{cal_text}.{state}")
