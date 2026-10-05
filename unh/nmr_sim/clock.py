"""Simulated clock: wall-clock time since start, times a speed factor."""

import time


class SimClock:
    """t_sim = start_at_s + speed * (wall() - t0), in seconds.

    Args:
        speed: simulated seconds per wall-clock second (e.g. 60)
        start_at_s: simulated time at creation, s (skip ahead in the timeline)
        wall: monotonic wall-clock source in seconds (injectable for tests)
    """

    def __init__(self, speed=1.0, start_at_s=0.0, wall=time.monotonic):
        if speed <= 0:
            raise ValueError("speed must be > 0")
        self.speed = float(speed)
        self.start_at_s = float(start_at_s)
        self._wall = wall
        self._t0 = wall()
        self.started_unix = time.time()

    def now_s(self):
        """Current simulated time, s."""
        return self.start_at_s + self.speed * (self._wall() - self._t0)
