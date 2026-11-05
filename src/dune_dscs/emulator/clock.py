from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    @property
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


@dataclass(slots=True)
class ScaledRealClock:
    """Wall clock whose waits can be accelerated or disabled."""

    time_scale: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_scale) or self.time_scale < 0:
            raise ValueError("time_scale must be finite and non-negative")

    @property
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        _validate_delay(seconds)
        await asyncio.sleep(seconds * self.time_scale)


def _validate_delay(seconds: float) -> None:
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("delay must be finite and non-negative")
