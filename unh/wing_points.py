"""Run tab: the wing fit's size as a number of points per side, with the fitted points marked (feature
``wing-points``).

JLab's "Polynomial Fit to Wings" (the default fit subtraction) fits a polynomial to two wing regions given on
the Analysis tab as four fractions of the sweep (``analysis: wings`` in pynmr_config.yaml, e.g. 0.01, 0.30, 0.70,
0.99). This adds a "Wing points per side: N" box in the corner of the Run tab's Baseline Subtracted plot (and of
the quadrature grid's Baseline Subtracted plots). N sets the inner two fractions symmetrically; the outer two,
JLab's skip of the outermost points, are kept. The default N is what the configured fractions give.

The Analysis tab's boxes stay the one setting: N writes into them, so the two never disagree, and the next
events use it. Changing N also redraws the last event's fit at once, for display. A dashed red curve over the
yellow fit marks exactly the points the fit used. For quadrature 90/270 deg records, whose background is fitted
jointly with KK(absorption) over the whole sweep (unh/quadrature/dispersion.py), it marks the whole sweep.
"""
import logging
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

log = logging.getLogger('PyNMR.unh.wing_points')

MARK_PEN = dict(color=(230, 0, 0), width=2.5, style=pg.QtCore.Qt.DashLine)


def used_mask(wings, n_points):
    """Points JLab's wing fit uses for these four fractions (bounds[0] < i < bounds[1], or bounds[2] < i < bounds[3])."""
    b = [w * n_points for w in wings]
    i = np.arange(n_points)
    return ((b[0] < i) & (i < b[1])) | ((b[2] < i) & (i < b[3]))


def points_per_side(wings, n_points):
    """(left, right) number of points the four fractions give."""
    m = used_mask(wings, n_points)
    half = n_points // 2
    return int(m[:half].sum()), int(m[half:].sum())


def wings_for(n, wings, n_points):
    """Four fractions giving exactly n points per side, keeping the outer two (JLab's edge skip) as they are."""
    w0, w3 = float(wings[0]), float(wings[3])
    first = math.floor(w0 * n_points) + 1              # first point used on the left
    last = math.ceil(w3 * n_points) - 1                # last point used on the right
    n = int(n)
    if n < 2 or first + n - 1 >= last - n + 1:
        raise ValueError(f'{n} points per side do not fit in {n_points} points')
    return [w0, (first + n - 0.5) / n_points, (last - n + 0.5) / n_points, w3]


def _len(x):
    return 0 if x is None else len(x)


def max_points(wings, n_points):
    first = math.floor(float(wings[0]) * n_points) + 1
    last = math.ceil(float(wings[3]) * n_points) - 1
    return max(2, (last - first + 1) // 2 - 1)


class _Corner(QObject):
    """Keeps a small widget in the top-right corner of a plot as the plot is resized."""

    def __init__(self, plot, widget):
        super().__init__(plot)
        self.plot, self.widget = plot, widget
        plot.installEventFilter(self)
        self.place()

    def place(self):
        self.widget.adjustSize()
        self.widget.move(max(0, self.plot.width() - self.widget.width() - 6), 2)    # in the title row
        self.widget.raise_()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Show):
            self.place()
        return False


class WingPoints:
    def __init__(self, mw):
        self.mw = mw
        anal = mw.anal_tab
        self.sub = next(o for o in anal.sub_opts if type(o).__name__ == 'PolyFitSub')
        for sb in self.sub.bounds_sb:
            sb.setDecimals(4)                              # 2 decimals would move the bounds in 5-point jumps
            sb.setSingleStep(0.002)
        self.n_points = len(mw.config.freq_list)
        left, right = points_per_side(self.sub.wings, self.n_points)
        self.default = left
        self.n = left
        self.spins, self.marks = [], {}
        self.quad = None
        self._busy = False
        run = mw.run_tab
        self.add_box(run.sub_wid)
        self.marks['jlab'] = run.sub_wid.plot([], [], pen=pg.mkPen(**MARK_PEN), connect='finite')
        jlab_update = run.update_event_plots
        def update_event_plots(*args, **kwargs):
            jlab_update(*args, **kwargs)
            self.draw_jlab()
        run.update_event_plots = update_event_plots
        self.refresh_enabled()

    # -- the box --------------------------------------------------------------------
    def add_box(self, plot):
        box = QWidget(plot)
        box.setStyleSheet('QWidget { background: transparent; font-size: 8pt; }')
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        h.addWidget(QLabel('Wing bins:'))
        spin = QSpinBox()
        spin.setMinimumWidth(spin.fontMetrics().horizontalAdvance('8888') + 36)   # room for 3-4 digits + arrows
        spin.setRange(2, max_points(self.sub.wings, self.n_points))
        spin.setValue(self.n)
        spin.setToolTip('Points (bins) used on EACH side by the wing fit (the dashed red part of the yellow curve).\n'
                        f'Default {self.default}, from the Analysis tab bounds in pynmr_config.yaml. '
                        'Sets those bounds; the next events use it.')
        spin.valueChanged.connect(self.set_n)
        h.addWidget(spin)
        box.corner = _Corner(plot, box)
        box.show()
        self.spins.append(spin)
        return spin

    def refresh_enabled(self):
        on = self.mw.anal_tab.sub_chosen == self.sub.result
        for s in self.spins:
            s.setEnabled(on)
            if not on:
                s.setToolTip('The Analysis tab is not using the polynomial wing fit.')

    # -- setting N --------------------------------------------------------------------
    def set_n(self, n):
        if self._busy:
            return
        try:
            wings = wings_for(n, self.sub.wings, self.n_points)
        except ValueError as e:
            log.warning(str(e))
            return
        self._busy = True
        try:
            for s in self.spins:
                s.setValue(int(n))
            for sb, w in zip(self.sub.bounds_sb, wings):
                sb.blockSignals(True)
                sb.setValue(w)
                sb.blockSignals(False)
            self.sub.change_wings()                         # JLab: stores the wings, shades them, re-analyses
            self.n = int(n)
        finally:
            self._busy = False
        log.info(f'Wing fit: {n} points per side (bounds {", ".join(f"{w:.4f}" for w in wings)}).')
        self.redraw()

    # -- marks --------------------------------------------------------------------------
    def mask_for(self, event):
        """Points the background fit of this record used."""
        n = _len(getattr(event, 'basesub', None))
        if getattr(event, 'quad_ref_deg', None) in (90, 270) and getattr(event, 'quad_sub_method', '') == 'joint KK':
            edge = 3
            q = getattr(self.mw, 'quadrature', None)
            if q is not None:
                edge = int((q.cfg.get('dispersion') or {}).get('edge', 3))
            m = np.zeros(n, dtype=bool)
            m[edge:n - edge] = True
            return m
        return used_mask(self.sub.wings, n)

    def marked(self, event, fitcurve):
        f = np.asarray(event.scan.freq_list, dtype=float)
        y = np.asarray(fitcurve, dtype=float)
        if len(f) == 0 or len(f) != len(y):
            return [], []
        m = self.mask_for(event)
        if len(m) != len(y):
            return [], []
        return f, np.where(m, y, np.nan)

    def display_fit(self, event):
        """The fit for this record with the present N (display only; the record keeps what it was analysed with)."""
        if getattr(event, 'quad_ref_deg', None) in (90, 270) and getattr(event, 'quad_sub_method', '') == 'joint KK':
            return np.asarray(event.fitcurve, dtype=float)
        if self.mw.anal_tab.sub_chosen != self.sub.result:
            return np.asarray(event.fitcurve, dtype=float)
        try:
            fit, _ = self.sub.result(event)
            return np.asarray(fit, dtype=float)
        except Exception:
            return np.asarray(event.fitcurve, dtype=float)

    def draw_jlab(self, refit=False):
        ev = getattr(self.mw, 'previous_event', None)
        if ev is None or not _len(getattr(ev, 'basesub', None)):
            self.marks['jlab'].setData([], [])
            return
        fit = self.display_fit(ev) if refit else np.asarray(ev.fitcurve, dtype=float)
        if refit and len(fit) == len(ev.basesub):
            run = self.mw.run_tab
            run.fit_plot.setData(ev.scan.freq_list, fit)
            run.fin_plot.setData(ev.scan.freq_list, np.asarray(ev.basesub, dtype=float) - fit)
        self.marks['jlab'].setData(*self.marked(ev, fit), connect='finite')

    def add_quad(self, plots):
        """QuadPlots: a box and marks on its Baseline Subtracted plots."""
        self.quad = plots
        self.add_box(plots.wids[('sub', 0)])
        for angle in (0, 90):
            self.marks[angle] = plots.wids[('sub', angle)].plot([], [], pen=pg.mkPen(**MARK_PEN), connect='finite')
        self.refresh_enabled()

    def draw_quad(self, event, refit=False):
        plots = getattr(self, 'quad', None)
        angle = getattr(event, 'quad_ref_deg', None)
        if plots is None or angle not in (0, 90):
            return
        fit = self.display_fit(event) if refit else np.asarray(getattr(event, 'fitcurve', []), dtype=float)
        if len(fit) != _len(getattr(event, 'basesub', None)):
            return
        if refit:
            plots.extra[('fitcurve', angle)].setData(event.scan.freq_list, fit)
            plots.curves[('fin', angle)].setData(event.scan.freq_list, np.asarray(event.basesub, dtype=float) - fit)
        self.marks[angle].setData(*self.marked(event, fit), connect='finite')

    def redraw(self):
        self.refresh_enabled()
        self.draw_jlab(refit=True)
        plots = getattr(self, 'quad', None)
        if plots is not None:
            for angle, ev in getattr(plots, 'last_events', {}).items():
                self.draw_quad(ev, refit=True)


def attach_wing_points(mw):
    """Never raises."""
    try:
        mw.wing_points = WingPoints(mw)
        mw.run_tab.wing_points = mw.wing_points
        q = getattr(mw, 'quadrature', None)
        if q is not None and q.ui is not None:
            mw.wing_points.add_quad(q.ui.plots)
        mw.anal_tab.sub_combo.currentIndexChanged.connect(lambda _: mw.wing_points.refresh_enabled())
        return mw.wing_points
    except Exception as e:
        log.error(f'Wing points box not added: {e}')
        return None
