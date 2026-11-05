from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..clock import Clock
from ..inventory import DeviceIdentity
from .base import BootTiming, DeviceModel, DevicePhase


@dataclass(frozen=True, slots=True)
class DaphneTiming:
    afe_reset_seconds: float = 0.0001
    afe_power_settle_seconds: float = 0.005
    channel_write_seconds: float = 0.0
    afe_write_seconds: float = 0.0
    delay_control_reset_seconds: float = 0.010
    serdes_reset_seconds: float = 0.010
    spy_snapshot_seconds: float = 0.001
    delay_taps: int = 512
    bitslip_taps: int = 16
    verification_reads: int = 4
    auto_align: bool = True


@dataclass(frozen=True, slots=True)
class DaphneChannelConfig:
    id: int
    trim: int = 0
    offset: int = 0
    gain: int = 0


@dataclass(frozen=True, slots=True)
class DaphneAfeConfig:
    id: int
    attenuation: int = 0
    bias: int = 0


@dataclass(frozen=True, slots=True)
class DaphneConfig:
    bias_control: int = 0
    threshold: int = 0
    channels: tuple[DaphneChannelConfig, ...] = ()
    afes: tuple[DaphneAfeConfig, ...] = ()


@dataclass(slots=True)
class DaphneChannelState:
    trim: int = 0
    offset: int = 0
    gain: int = 0
    threshold: int = 0
    configured: bool = False
    record_count: int = 0
    busy_count: int = 0
    full_count: int = 0


@dataclass(slots=True)
class DaphneAfeState:
    attenuation: int = 0
    bias: int = 0
    powered: bool = False
    configured: bool = False
    aligned: bool = False


class DaphneModel(DeviceModel):
    def __init__(
        self,
        identity: DeviceIdentity,
        clock: Clock,
        boot_timing: BootTiming = BootTiming(),
        timing: DaphneTiming = DaphneTiming(),
    ) -> None:
        super().__init__(identity, clock, boot_timing)
        self.timing = timing
        self.channels = [DaphneChannelState() for _ in range(40)]
        self.afes = [DaphneAfeState() for _ in range(5)]
        self.bias_control = 0
        self.configuration_generation = 0
        self.configuration_permitted = True
        self.telemetry: dict[str, float] = {
            "v_bias_0": 0.0,
            "v_bias_1": 0.0,
            "v_bias_2": 0.0,
            "v_bias_3": 0.0,
            "v_bias_4": 0.0,
            "power_minus5v": 0.0,
            "power_plus2p5v": 0.0,
            "power_ce": 0.0,
            "temperature": 0.0,
        }
        initial_telemetry = identity.attributes.get("initial_telemetry", {})
        if not isinstance(initial_telemetry, Mapping):
            raise ValueError("initial_telemetry must be a mapping")
        unknown = sorted(set(initial_telemetry) - set(self.telemetry))
        if unknown:
            raise ValueError(f"unknown initial DAPHNE telemetry fields: {', '.join(unknown)}")
        self.telemetry.update(
            {str(name): float(value) for name, value in initial_telemetry.items()}
        )

    def set_configuration_permit(self, granted: bool) -> None:
        self.configuration_permitted = granted

    def nominal_configure_seconds(self, config: DaphneConfig) -> float:
        timing = self.timing
        duration = timing.afe_reset_seconds + 2 * timing.afe_power_settle_seconds
        duration += len(config.channels) * 2 * timing.channel_write_seconds
        duration += len(config.afes) * timing.afe_write_seconds
        if timing.auto_align:
            snapshots = 5 * (timing.delay_taps + timing.bitslip_taps + timing.verification_reads)
            duration += timing.delay_control_reset_seconds + timing.serdes_reset_seconds
            duration += snapshots * timing.spy_snapshot_seconds
        return duration

    async def configure(self, config: DaphneConfig) -> int:
        self._validate_config(config)
        async with self.command_lock:
            self.require_ready()
            if not self.configuration_permitted:
                raise PermissionError(f"configuration permit denied for {self.id}")
            generation = self.power_generation
            self._transition(DevicePhase.CONFIGURING)
            try:
                for afe in self.afes:
                    afe.powered = False
                    afe.aligned = False
                await self.clock.sleep(self.timing.afe_reset_seconds)
                self.require_power_generation(generation)
                for afe in self.afes:
                    afe.powered = True
                await self.clock.sleep(self.timing.afe_power_settle_seconds)

                for requested in config.channels:
                    await self.clock.sleep(self.timing.channel_write_seconds)
                    await self.clock.sleep(self.timing.channel_write_seconds)
                    target = self.channels[requested.id]
                    target.trim = requested.trim
                    target.offset = requested.offset
                    target.gain = requested.gain
                    target.threshold = config.threshold & 0x0FFFFFFF
                    target.configured = True

                for requested in config.afes:
                    await self.clock.sleep(self.timing.afe_write_seconds)
                    target = self.afes[requested.id]
                    target.attenuation = requested.attenuation
                    target.bias = requested.bias
                    target.configured = True

                self.bias_control = config.bias_control
                await self.clock.sleep(self.timing.afe_power_settle_seconds)
                if self.timing.auto_align:
                    await self.clock.sleep(self.timing.delay_control_reset_seconds)
                    await self.clock.sleep(self.timing.serdes_reset_seconds)
                    per_afe = self.timing.spy_snapshot_seconds * (
                        self.timing.delay_taps
                        + self.timing.bitslip_taps
                        + self.timing.verification_reads
                    )
                    for afe in self.afes:
                        await self.clock.sleep(per_afe)
                        afe.aligned = True
                self.require_power_generation(generation)
                self.configuration_generation += 1
                self._transition(DevicePhase.READY)
                return self.configuration_generation
            except Exception:
                if self.powered:
                    self._transition(DevicePhase.FAULTED)
                raise

    @staticmethod
    def _validate_config(config: DaphneConfig) -> None:
        for channel in config.channels:
            if not 0 <= channel.id < 40:
                raise ValueError(f"DAPHNE channel out of range: {channel.id}")
        for afe in config.afes:
            if not 0 <= afe.id < 5:
                raise ValueError(f"DAPHNE AFE out of range: {afe.id}")
            if not 0 <= afe.attenuation <= 4095 or not 0 <= afe.bias <= 4095:
                raise ValueError(f"DAPHNE AFE DAC value out of range: {afe.id}")
