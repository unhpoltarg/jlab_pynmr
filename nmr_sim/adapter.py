"""DAQ adapter: the only nmr_sim module PyNMR imports (from hardware/daq.py).

It speaks PyNMR's DAQ chunk contract using plain values, so nmr_sim does not
depend on PyNMR's Config or settings layout.
"""

import time

import numpy as np

from .simulator import get_simulator


class SimDAQ:
    """Simulated DAQ source.

    Args:
        sim_cfg: nmr_sim config dict (settings['nmr_sim'])
        freq_MHz: sweep frequency list, MHz (config.freq_list)
        sweeps_per_chunk: sweeps averaged per returned chunk
    """

    def __init__(self, sim_cfg, freq_MHz, sweeps_per_chunk):
        self.freq_MHz = np.array(freq_MHz, dtype=float)
        self.n = int(sweeps_per_chunk)
        self.sim = get_simulator(sim_cfg, self.freq_MHz)
        self.sweep_time_s = float(self.sim.cfg["sweep_time_s"])
        self.message = "DAQ Test mode (nmr_sim simulation)."
        self.name = "Test (nmr_sim)"

    def get_chunk(self):
        """Return (chunk_num, num_in_chunk, phase, diode).

        chunk_num is 0 (as in replay, so RunThread's lost-chunk check passes);
        phase and diode are per-sweep averages in V, one value per frequency.
        """
        if self.sweep_time_s > 0:
            time.sleep(self.sweep_time_s * self.n)
        phase, diode, _ = self.sim.sweep(self.freq_MHz, self.n)
        return (0, self.n, phase.astype(float), diode.astype(float))

    def set_dac(self, dac_v, dac_c):
        """Tune-tab DAC: value 0..1; channel 1 phase, 2 diode, 3 both, 0 no-op."""
        self.sim.set_dac(dac_v, dac_c)
        return True
