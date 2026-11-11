"""Repeat recorded response waits without blocking the event loop."""

import asyncio
import itertools
import json
import math
from pathlib import Path


class Timing:
    def __init__(self, delays):
        self.samples = {}
        for operation, values in delays.items():
            if (not isinstance(values, list) or not values or any(
                    isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) or v < 0 for v in values)):
                raise ValueError(f"{operation}: delays_ms must contain finite, nonnegative numbers")
            self.samples[operation] = itertools.cycle(values)

    @classmethod
    def load(cls, path, kind):
        if path is None:
            return cls({})
        profile = json.loads(Path(path).read_text())
        if (not isinstance(profile, dict) or profile.get("kind") != kind
                or not isinstance(profile.get("delays_ms"), dict)):
            raise ValueError("timing profile must match the emulator kind and contain delays_ms")
        return cls(profile["delays_ms"])

    def seconds(self, operation):
        values = self.samples.get(operation)
        return next(values) / 1000 if values is not None else 0

    async def wait(self, operation):
        delay = self.seconds(operation)
        if delay:
            await asyncio.sleep(delay)
