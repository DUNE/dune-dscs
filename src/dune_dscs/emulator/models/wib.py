from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..clock import Clock
from ..inventory import DeviceIdentity
from .base import BootTiming, DeviceModel, DevicePhase


@dataclass(frozen=True, slots=True)
class WibTiming:
    # Conservative explicit-wait envelope from dune-wib-firmware's four-FEMB
    # ConfigureWIB path: 4 FEMBs * 8 COLDADCs * 500 ms calibration plus as
    # many as 10 * 10 ms SPI-verification waits. I2C and other hardware time
    # are not included, so physical measurements may be longer.
    configure_seconds: float = 16.100
    femb_power_seconds: float = 0.050
    timing_reset_seconds: float = 0.010


@dataclass(frozen=True, slots=True)
class WibConfig:
    cold: bool = False
    pulser: bool = False
    enabled_fembs: tuple[bool, bool, bool, bool] = (True, True, True, True)


class WibModel(DeviceModel):
    def __init__(
        self,
        identity: DeviceIdentity,
        clock: Clock,
        boot_timing: BootTiming = BootTiming(),
        timing: WibTiming = WibTiming(),
    ) -> None:
        super().__init__(identity, clock, boot_timing)
        self.timing = timing
        self.femb_power = [False, False, False, False]
        self.configuration_generation = 0
        self.configuration_permitted = True
        self.last_config: WibConfig | None = None
        initial_sensors = identity.attributes.get("initial_sensors", {})
        if not isinstance(initial_sensors, Mapping):
            raise ValueError("initial_sensors must be a mapping")
        self.sensors = {str(name): float(value) for name, value in initial_sensors.items()}
        self.timing_locked = bool(identity.attributes.get("initial_timing_locked", False))
        self.power_configuration: dict[str, float] = {}
        self.registers: dict[int, int] = {}
        self.coldata_registers: dict[tuple[int, int, int, int, int], int] = {}
        self.software_version = "detector-control-emulator"
        self.firmware_timestamp = 0
        self.fake_time = 0
        self.log = bytearray(b"detector-control-emulator: WIB service ready\n")
        self.boot_log = b"detector-control-emulator: emulated PetaLinux boot complete\n"
        self.update_generation = 0
        self.last_script = b""

    def set_configuration_permit(self, granted: bool) -> None:
        self.configuration_permitted = granted

    async def configure(self, config: WibConfig) -> int:
        async with self.command_lock:
            self.require_ready()
            if not self.configuration_permitted:
                raise PermissionError(f"configuration permit denied for {self.id}")
            generation = self.power_generation
            self._transition(DevicePhase.CONFIGURING)
            await self.clock.sleep(self.timing.configure_seconds)
            self.require_power_generation(generation)
            self.femb_power[:] = config.enabled_fembs
            self.last_config = config
            self.configuration_generation += 1
            self._transition(DevicePhase.READY)
            return self.configuration_generation

    async def set_femb_power(self, index: int, enabled: bool) -> None:
        if not 0 <= index < 4:
            raise ValueError(f"FEMB index out of range: {index}")
        async with self.command_lock:
            self.require_ready()
            await self.clock.sleep(self.timing.femb_power_seconds)
            self.femb_power[index] = enabled

    async def apply_femb_power(self, enabled: tuple[bool, bool, bool, bool]) -> None:
        async with self.command_lock:
            self.require_ready()
            await self.clock.sleep(self.timing.femb_power_seconds)
            self.femb_power[:] = enabled

    async def reset_timing(self) -> None:
        async with self.command_lock:
            self.require_ready()
            self.timing_locked = False
            await self.clock.sleep(self.timing.timing_reset_seconds)
            self.timing_locked = True

    def append_log(self, message: str) -> None:
        self.log.extend(message.encode("utf-8", errors="replace"))
