from __future__ import annotations

import asyncio
from collections.abc import Iterable
from contextlib import suppress

import zmq
import zmq.asyncio
from google.protobuf.message import DecodeError, Message

from ..models import WibConfig, WibModel
from ._generated import wib_pb2 as pb


class WibZmqFleet:
    """Expose many WIB models through the production REP/protobuf contract."""

    def __init__(
        self,
        models: Iterable[WibModel],
        context: zmq.asyncio.Context | None = None,
    ) -> None:
        self.models = tuple(models)
        self.context = context or zmq.asyncio.Context()
        self._owns_context = context is None
        self._listeners: list[_WibListener] = []

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def start(self) -> None:
        if self._listeners:
            raise RuntimeError("WIB ZMQ fleet is already started")
        try:
            for model in self.models:
                endpoint = model.identity.endpoint
                if endpoint is None or endpoint.scheme != "tcp":
                    raise ValueError(f"WIB {model.id} requires a tcp endpoint")
                listener = _WibListener(model, self.context)
                listener.start()
                self._listeners.append(listener)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        listeners, self._listeners = self._listeners, []
        await asyncio.gather(*(listener.close() for listener in listeners))
        if self._owns_context:
            self.context.destroy(linger=0)


class _WibListener:
    def __init__(self, model: WibModel, context: zmq.asyncio.Context) -> None:
        self.model = model
        self.socket = context.socket(zmq.REP)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.task: asyncio.Task[None] | None = None
        self.side_tasks: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        endpoint = self.model.identity.endpoint
        assert endpoint is not None
        self.socket.bind(endpoint.uri)
        self.task = asyncio.create_task(self._serve(), name=f"wib-zmq:{self.model.id}")

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        for task in self.side_tasks:
            task.cancel()
        if self.side_tasks:
            await asyncio.gather(*self.side_tasks, return_exceptions=True)
        self.side_tasks.clear()
        self.socket.close(linger=0)

    async def _serve(self) -> None:
        while True:
            payload = await self.socket.recv()
            if not self.model.available:
                await self.socket.send(b"")
                continue
            try:
                reply = await self._dispatch(payload)
            except Exception:
                reply = b""
            await self.socket.send(reply)

    async def _dispatch(self, payload: bytes) -> bytes:
        command = pb.Command()
        try:
            command.ParseFromString(payload)
        except DecodeError:
            return b""
        packed = command.cmd

        if _is(packed, pb.GetSensors):
            return _sensor_reply(self.model).SerializeToString()

        if _is(packed, pb.GetFEMBStatus):
            request = _unpack(packed, pb.GetFEMBStatus())
            return _femb_status_reply(self.model, request.read_voltages).SerializeToString()

        if _is(packed, pb.ResetTiming):
            await self.model.reset_timing()
            return _timing_reply(self.model).SerializeToString()

        if _is(packed, pb.GetTimingStatus):
            return _timing_reply(self.model).SerializeToString()

        if _is(packed, pb.GetTimestamp):
            timestamp = self.model.firmware_timestamp
            return pb.GetTimestamp.Timestamp(
                timestamp=timestamp,
                day=(timestamp >> 27) & 0x1F,
                month=(timestamp >> 23) & 0x0F,
                year=(timestamp >> 17) & 0x3F,
                hour=(timestamp >> 12) & 0x1F,
                min=(timestamp >> 6) & 0x3F,
                sec=timestamp & 0x3F,
            ).SerializeToString()

        if _is(packed, pb.GetSWVersion):
            return pb.GetSWVersion.Version(version=self.model.software_version).SerializeToString()

        if _is(packed, pb.Script):
            request = _unpack(packed, pb.Script())
            self.model.last_script = bytes(request.script)
            source = "file" if request.file else "inline"
            self.model.append_log(f"executed emulated {source} script\n")
            return pb.Status(success=True, extra=b"emulated script complete\n").SerializeToString()

        if _is(packed, pb.ReadDaqSpy):
            request = _unpack(packed, pb.ReadDaqSpy())
            if request.deframe:
                return pb.ReadDaqSpy.DeframedDaqSpy(
                    crate_num=int(self.model.identity.attributes.get("crate", 0)),
                    wib_num=int(self.model.identity.attributes.get("wib", 0)),
                    num_samples=0,
                    deframed_samples=b"",
                    deframed_timestamps=b"",
                    success=True,
                ).SerializeToString()
            return pb.ReadDaqSpy.DaqSpy(
                buf0=b"" if request.buf0 else b"",
                buf1=b"" if request.buf1 else b"",
                success=True,
            ).SerializeToString()

        if _is(packed, pb.LogControl):
            request = _unpack(packed, pb.LogControl())
            contents = self.model.boot_log if request.boot_log else bytes(self.model.log)
            if not request.return_log and not request.boot_log:
                contents = b""
            if request.clear_log:
                self.model.log.clear()
            return pb.LogControl.Log(contents=contents).SerializeToString()

        if _is(packed, pb.ConfigurePower):
            request = _unpack(packed, pb.ConfigurePower())
            self.model.power_configuration = {
                "dc2dc_o1": request.dc2dc_o1,
                "dc2dc_o2": request.dc2dc_o2,
                "dc2dc_o3": request.dc2dc_o3,
                "dc2dc_o4": request.dc2dc_o4,
                "ldo_a0": request.ldo_a0,
                "ldo_a1": request.ldo_a1,
            }
            return pb.Status(success=True, extra=b"emulated power configuration\n").SerializeToString()

        if _is(packed, pb.PowerWIB):
            request = _unpack(packed, pb.PowerWIB())
            await self.model.apply_femb_power((request.femb0, request.femb1, request.femb2, request.femb3))
            return pb.Status(success=True, extra=b"emulated FEMB power transition\n").SerializeToString()

        if _is(packed, pb.ConfigureWIB):
            request = _unpack(packed, pb.ConfigureWIB())
            enabled = tuple(item.enabled for item in request.fembs[:4])
            enabled = enabled + (False,) * (4 - len(enabled))
            try:
                generation = await self.model.configure(
                    WibConfig(cold=request.cold, pulser=request.pulser, enabled_fembs=enabled)
                )
                return pb.Status(
                    success=True, extra=f"emulated WIB configuration generation {generation}\n".encode()
                ).SerializeToString()
            except Exception as error:
                return pb.Status(success=False, extra=f"{error}\n".encode()).SerializeToString()

        if _is(packed, pb.Peek):
            request = _unpack(packed, pb.Peek())
            return pb.RegValue(addr=request.addr, value=self.model.registers.get(request.addr, 0)).SerializeToString()

        if _is(packed, pb.Poke):
            request = _unpack(packed, pb.Poke())
            self.model.registers[request.addr] = request.value
            return pb.RegValue(addr=request.addr, value=request.value).SerializeToString()

        if _is(packed, pb.CDPeek):
            request = _unpack(packed, pb.CDPeek())
            key = _coldata_key(request)
            return _coldata_reply(request, self.model.coldata_registers.get(key, 0)).SerializeToString()

        if _is(packed, pb.CDPoke):
            request = _unpack(packed, pb.CDPoke())
            self.model.coldata_registers[_coldata_key(request)] = request.data & 0xFF
            return _coldata_reply(request, request.data & 0xFF).SerializeToString()

        if _is(packed, pb.SetFakeTime):
            request = _unpack(packed, pb.SetFakeTime())
            self.model.fake_time = request.time
            return pb.Empty().SerializeToString()

        if any(
            _is(packed, message_type)
            for message_type in (pb.StartFakeTime, pb.CDFastCmd, pb.Calibrate, pb.Recompile)
        ):
            if _is(packed, pb.Calibrate) or _is(packed, pb.Recompile):
                return pb.Status(success=True, extra=b"emulated command complete\n").SerializeToString()
            return pb.Empty().SerializeToString()

        if _is(packed, pb.Reboot):
            self._schedule_reboot("reboot")
            return pb.Empty().SerializeToString()

        if _is(packed, pb.Update):
            _unpack(packed, pb.Update())
            self.model.update_generation += 1
            self.model.append_log(
                f"accepted emulated update generation {self.model.update_generation}\n"
            )
            self._schedule_reboot("update")
            return pb.Empty().SerializeToString()

        return b""

    async def _reboot(self) -> None:
        await self.model.set_power(False)
        await self.model.set_power(True)

    def _schedule_reboot(self, reason: str) -> None:
        task = asyncio.create_task(self._reboot(), name=f"wib-{reason}:{self.model.id}")
        self.side_tasks.add(task)
        task.add_done_callback(self.side_tasks.discard)


def _is(packed: object, message_type: type[Message]) -> bool:
    return packed.Is(message_type.DESCRIPTOR)  # type: ignore[attr-defined]


def _unpack(packed: object, message: Message) -> Message:
    if not packed.Unpack(message):  # type: ignore[attr-defined]
        raise DecodeError(f"could not unpack {message.DESCRIPTOR.full_name}")
    return message


def _sensor_reply(model: WibModel) -> Message:
    sensors = pb.GetSensors.Sensors()
    sensors.ltc2990_4e_voltages.extend([5.0, 5.0, 1.2, 0.6])
    sensors.ltc2990_4c_voltages.extend([1.2, 1.2, 3.3, 3.3])
    sensors.ltc2991_48_voltages.extend([0.85, 0.85, 0.9, 0.9, 2.5, 2.5, 1.8, 1.8])
    sensors.ad7414_49_temp = model.sensors.get("ad7414_49_temp", 28.0)
    sensors.ad7414_4d_temp = model.sensors.get("ad7414_4d_temp", 29.0)
    sensors.ad7414_4a_temp = model.sensors.get("ad7414_4a_temp", 30.0)
    sensors.ltc2499_15_temps.extend([model.sensors.get(f"temperature_{index}", 27.0) for index in range(7)])
    for field_name in (
        "femb0_dc2dc_ltc2991_voltages",
        "femb1_dc2dc_ltc2991_voltages",
        "femb2_dc2dc_ltc2991_voltages",
        "femb3_dc2dc_ltc2991_voltages",
        "femb_ldo_a0_ltc2991_voltages",
        "femb_ldo_a1_ltc2991_voltages",
        "femb_bias_ltc2991_voltages",
    ):
        getattr(sensors, field_name).extend([0.0] * 8)
    return sensors


def _femb_status_reply(model: WibModel, read_voltages: bool) -> Message:
    response = pb.GetFEMBStatus.FEMBStatus()
    response.femb_power.extend(model.femb_power)
    if read_voltages:
        powered = [1.0 if enabled else 0.0 for enabled in model.femb_power]
        response.bias_voltage.extend(5.0 * value for value in powered)
        response.bias_current.extend(0.01 * value for value in powered)
        response.larasic_voltage.extend(2.5 * value for value in powered)
        response.larasic_current.extend(0.4 * value for value in powered)
        response.coldadc_voltage.extend(1.8 * value for value in powered)
        response.coldadc_current.extend(0.2 * value for value in powered)
        response.coldata_voltage.extend(1.2 * value for value in powered)
        response.coldata_current.extend(0.2 * value for value in powered)
    return response


def _timing_reply(model: WibModel) -> Message:
    return pb.GetTimingStatus.TimingStatus(ept_status=0x108 if model.timing_locked else 0)


def _coldata_key(request: Message) -> tuple[int, int, int, int, int]:
    return (
        request.femb_idx,  # type: ignore[attr-defined]
        request.coldata_idx,  # type: ignore[attr-defined]
        request.chip_addr,  # type: ignore[attr-defined]
        request.reg_page,  # type: ignore[attr-defined]
        request.reg_addr,  # type: ignore[attr-defined]
    )


def _coldata_reply(request: Message, data: int) -> Message:
    return pb.CDRegValue(
        femb_idx=request.femb_idx,  # type: ignore[attr-defined]
        coldata_idx=request.coldata_idx,  # type: ignore[attr-defined]
        chip_addr=request.chip_addr,  # type: ignore[attr-defined]
        reg_page=request.reg_page,  # type: ignore[attr-defined]
        reg_addr=request.reg_addr,  # type: ignore[attr-defined]
        data=data,
    )
