"""Headless TestSimQuad session: calibrate, take baselines at 0 and 90 deg, run pairs, then cycle4.

Run from a scratch copy of the worktree (runs rewrite tracked files):
    conda run -n pynmr --no-capture-output python drive_quad.py
"""
import os
import sys
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QItemSelectionModel, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from gui.main_window import MainWindow
from core import EventType

win = MainWindow('pynmr_config.yaml', profile='TestSimQuad')
ctrl = win.quadrature
assert ctrl is not None, 'quadrature not attached'
log = lambda *a: print('[drive]', *a, flush=True)

finished = []
win.event_bus.subscribe(EventType.EVENT_FINISHED, lambda d: finished.append(d.get('event')))

# operator tunes: Real 23.80 %, Imag 40.76 % (Tune tab spinbox, which also sends the DAC)
win.tune_tab.phase_spin.setValue(23.80)
ctrl.select_tune(90)
win.tune_tab.phase_spin.setValue(40.76)
ctrl.select_tune(0)
log('tunes', ctrl.sched.tunes)

state = {'step': 'cal', 't': time.time(), 'target': 0}


def idle():
    rt = getattr(win.run_tab, 'run_thread', None)
    b = win.run_tab.run_button
    return (not b.isChecked() and b.isEnabled() and (rt is None or not rt.isRunning())
            and not win.analysis_in_progress and not win.pending_next_run)


def run_events(n, label):
    win.run_tab.label_combo.setCurrentText(label)
    state['target'] = len(finished) + n
    win.run_tab.run_button.click()          # Run


def tick():
    s = state['step']
    if s == 'cal':
        ctrl.start_calibration()
        state['step'] = 'cal_wait'
    elif s == 'cal_wait':
        if not ctrl.calibrating() and ctrl.cal_thread is not None and ctrl.cal_thread.isFinished():
            log('calibration:', ctrl.ui.cal_label.text())
            ctrl.ui.check.setChecked(True)
            log('quadrature on:', ctrl.sched.active, ctrl.ui.run_label.text())
            run_events(6, 'Baseline')
            state['step'] = 'base_wait'
    elif s == 'base_wait':
        if len(finished) >= state['target'] and win.run_tab.run_button.isChecked():
            win.run_tab.run_button.click()  # Finish
        if len(finished) >= state['target'] and idle():
            bt = win.base_tab
            bt.use_last()
            model = bt.event_model
            sel = bt.event_table.selectionModel()
            rows = [r for r in range(model.rowCount()) if model.item(r, 7).text() == 'Baseline']
            for r in rows:
                sel.select(model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
            bt.select_event()
            bt.set_base()
            log('baselines set from rows', rows, 'angles', sorted(ctrl.baselines))
            run_events(20, 'Polarize')
            state['step'] = 'pol_wait'
    elif s == 'pol_wait':
        if len(finished) >= state['target'] and win.run_tab.run_button.isChecked():
            win.run_tab.run_button.click()
        if len(finished) >= state['target'] and idle():
            ctrl.ui.check.setChecked(False)
            ctrl.use_suggested(180)
            ctrl.use_suggested(270)
            ctrl.select_tune(0)
            ctrl.ui.seq_combo.setCurrentIndex(list(ctrl.ui.sequences).index('cycle4'))
            ctrl.ui.check.setChecked(True)
            log('cycle4 tunes', ctrl.sched.tunes, ctrl.ui.run_label.text())
            run_events(8, 'Polarize')
            state['step'] = 'c4_wait'
    elif s == 'c4_wait':
        if len(finished) >= state['target'] and win.run_tab.run_button.isChecked():
            win.run_tab.run_button.click()
        if len(finished) >= state['target'] and idle():
            log('done; events', len(finished), 'eventfile', win.eventfile_name, 'config phase_vout', win.config.phase_vout)
            state['step'] = 'quit'
            win.close()
            app.quit()
            return
    if time.time() - state['t'] > 1800:
        log('TIMEOUT in', s)
        app.quit()
        return
    QTimer.singleShot(250, tick)


QTimer.singleShot(500, tick)
app.exec()
log('exit')
