"""Synthetic sensor drift and counters, driven by elapsed time rather than reads."""

import math
import time


class Telemetry:
    def __init__(self, seed=0, period=60, clock=time.monotonic):
        if not math.isfinite(period) or period <= 0:
            raise ValueError("variation period must be positive and finite")
        self.seed, self.period, self.clock = seed, period, clock
        self.started = clock()

    def elapsed(self):
        return max(0, self.clock() - self.started)

    def analog(self, nominal, amplitude, channel=0):
        phase = (self.seed * .61803398875 + channel * .38196601125) % 1
        return nominal + amplitude * math.sin(math.tau * (self.elapsed() / self.period + phase))

    def counter(self, rate):
        return int(self.elapsed() * rate) % (2**64)
