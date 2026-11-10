"""Sweep counts as a fixed 64 times a whole number the operator sets (feature ``sweep-blocks``).

- Run tab, Sweeps per Event: 64 x N, N default 1 (64 sweeps; JLab's default was 640).
- Tune tab, Sweeps for Running Average: 64 x N, N default 1 (one 64-sweep tune chunk; more makes the plot lag
  the knobs by about 1.8 s per chunk).

The box sends sweeps in chunks of 64 and returned 64 when asked for 32, so totals are kept to whole chunks
(``tune_per_chunk`` is 64 in pynmr_config.yaml for the same reason). JLab's own line edits stay in place,
hidden, and are kept equal to 64 x N, so JLab's code reads them unchanged.
"""
import logging

from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QWidget

BLOCK = 64            # sweeps per block, fixed (the box's chunk size)
DEFAULT_BLOCKS = 1    # 64 sweeps (JLab's default was 640)
MAX_SWEEPS = 65535    # the FPGA register is 16 bits

log = logging.getLogger('PyNMR.unh.sweep_blocks')


def _blocks_row(tip):
    """A '64 x [N] = total' widget: (widget, spin, total label)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(QLabel(f'{BLOCK} ×'))
    spin = QSpinBox()
    spin.setRange(1, MAX_SWEEPS // BLOCK)
    spin.setToolTip(tip)
    h.addWidget(spin)
    total = QLabel('')
    h.addWidget(total)
    h.addStretch(1)
    return w, spin, total


class SweepBlocks:
    def __init__(self, run_tab):
        self.tab = run_tab
        line = run_tab.controls_lines['sweeps']
        item = run_tab.parent.config.controls['sweeps']
        layout = run_tab.controls_layout
        row = next(r for r in range(layout.rowCount())
                   if layout.itemAtPosition(r, 1) is not None and layout.itemAtPosition(r, 1).widget() is line)
        self.widget, self.spin, self.total = _blocks_row(
            f'Sweeps per event = {BLOCK} × this number (the box sends sweeps in chunks of {BLOCK})')
        line.hide()
        layout.addWidget(self.widget, row, 1)
        run_tab.controls_labels['sweeps'].setText('Sweeps per Event')

        n = int(item.value) // BLOCK if int(item.value) % BLOCK == 0 else DEFAULT_BLOCKS
        if int(item.value) != BLOCK * n:
            log.info(f'Sweeps per Event {item.value} is not a multiple of {BLOCK}; set to {BLOCK} x {n} = {BLOCK * n}.')
            item.set_config(str(BLOCK * n))
        self.spin.setValue(n)
        self.spin.valueChanged.connect(self.changed)
        self.changed(n)
        self.spin.setEnabled(run_tab.lock_button.isChecked())
        run_tab.lock_button.toggled.connect(self.spin.setEnabled)    # editable only while unlocked, like JLab's box

    def changed(self, n):
        sweeps = BLOCK * int(n)
        self.total.setText(f'= {sweeps}')
        self.tab.controls_lines['sweeps'].setText(str(sweeps))     # JLab's box; read by Set as before


class TuneBlocks:
    """Tune tab: Sweeps for Running Average as 64 x N."""
    DEFAULT = 1

    def __init__(self, tune_tab):
        self.tab = tune_tab
        line = tune_tab.avg_value
        lay = tune_tab.tune_box.layout()
        self.widget, self.spin, self.total = _blocks_row(
            f'Sweeps in the running average = {BLOCK} × this number (one tune chunk is {BLOCK} sweeps)')
        lay.insertWidget(lay.indexOf(line) + 1, self.widget)
        line.hide()
        self.spin.setValue(self.DEFAULT)
        self.spin.valueChanged.connect(self.changed)
        self.changed(self.DEFAULT)

    def changed(self, n):
        sweeps = BLOCK * int(n)
        self.total.setText(f'= {sweeps}')
        self.tab.avg_value.setText(str(sweeps))           # JLab's box; its textChanged sets the running average


def attach_tune_blocks(tune_tab):
    """Replace the Tune tab's running-average box with 64 x N. Never raises."""
    try:
        tune_tab.sweep_blocks = TuneBlocks(tune_tab)
        return tune_tab.sweep_blocks
    except Exception as e:
        log.error(f'Sweeps for Running Average left as JLab has it: {e}')
        return None


def attach_sweep_blocks(run_tab):
    """Replace the Sweeps per Event box with 64 x N. Never raises."""
    try:
        if 'sweeps' not in getattr(run_tab, 'controls_lines', {}):
            return None
        run_tab.sweep_blocks = SweepBlocks(run_tab)
        return run_tab.sweep_blocks
    except Exception as e:
        log.error(f'Sweeps per Event left as JLab has it: {e}')
        return None
