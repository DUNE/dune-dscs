from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum

from ..clock import Clock
from ..inventory import DeviceIdentity


class DevicePhase(str, Enum):
    POWERED_OFF = "powered_off"
    FIRMWARE_LOADING = "firmware_loading"
    OPERATING_SYSTEM_BOOTING = "operating_system_booting"
    SERVICE_STARTING = "service_starting"
    READY = "ready"
    CONFIGURING = "configuring"
    FAULTED = "faulted"


class DeviceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BootTiming:
    firmware_seconds: float = 0.0
    operating_system_seconds: float = 0.0
    service_seconds: float = 0.0


class DeviceModel:
    def __init__(self, identity: DeviceIdentity, clock: Clock, boot_timing: BootTiming = BootTiming()) -> None:
        self.identity = identity
        self.clock = clock
        self.boot_timing = boot_timing
        self.phase = DevicePhase.POWERED_OFF
        self.powered = False
        self.last_transition = clock.now
        self.command_lock = asyncio.Lock()
        self._power_generation = 0

    @property
    def id(self) -> str:
        return self.identity.id

    @property
    def available(self) -> bool:
        return self.powered and self.phase == DevicePhase.READY

    async def set_power(self, enabled: bool) -> None:
        self._power_generation += 1
        generation = self._power_generation
        self.powered = enabled
        if not enabled:
            self._transition(DevicePhase.POWERED_OFF)
            return
        self._transition(DevicePhase.FIRMWARE_LOADING)
        await self.clock.sleep(self.boot_timing.firmware_seconds)
        if not self._is_current_power(generation):
            return
        self._transition(DevicePhase.OPERATING_SYSTEM_BOOTING)
        await self.clock.sleep(self.boot_timing.operating_system_seconds)
        if not self._is_current_power(generation):
            return
        self._transition(DevicePhase.SERVICE_STARTING)
        await self.clock.sleep(self.boot_timing.service_seconds)
        if self._is_current_power(generation):
            self._transition(DevicePhase.READY)

    def require_ready(self) -> None:
        if not self.available:
            raise DeviceUnavailable(f"{self.id} is not ready (phase={self.phase.value})")

    def require_power_generation(self, generation: int) -> None:
        if not self._is_current_power(generation):
            raise DeviceUnavailable(f"{self.id} lost power during the operation")

    @property
    def power_generation(self) -> int:
        return self._power_generation

    def _is_current_power(self, generation: int) -> bool:
        return self.powered and generation == self._power_generation

    def _transition(self, phase: DevicePhase) -> None:
        self.phase = phase
        self.last_transition = self.clock.now
