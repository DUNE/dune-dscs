"""Stateful WIB protobuf request/reply handler."""

from google.protobuf.message import DecodeError, Message

from .protocols._generated import wib_pb2 as pb


class Wib:
    def __init__(self, telemetry=None):
        self.telemetry = telemetry
        self.femb_power = [False] * 4
        self.configuration_generation = 0
        self.sensors = {}
        self.timing_locked = False
        self.power_configuration = {}
        self.registers = {}
        self.coldata_registers = {}
        self.software_version = "detector-control-emulator"
        self.firmware_timestamp = 0
        self.fake_time = 0
        self.log = bytearray(b"emulated WIB ready\n")
        self.boot_log = b"emulated WIB boot complete\n"
        self.update_generation = 0
        self.last_script = b""

    def append_log(self, message):
        self.log.extend(message.encode())

    async def configure(self, enabled):
        self.femb_power[:] = enabled
        self.configuration_generation += 1
        return self.configuration_generation

    async def apply_femb_power(self, enabled):
        self.femb_power[:] = enabled

    async def reset_timing(self):
        self.timing_locked = True

    async def reply(self, payload: bytes) -> bytes:
        # Requests wrap Any in Command.cmd; replies are raw response messages.
        command = pb.Command()
        try:
            command.ParseFromString(payload)
        except DecodeError:
            return b""
        packed = command.cmd

        if _is(packed, pb.GetSensors):
            return _sensor_reply(self).SerializeToString()

        if _is(packed, pb.GetFEMBStatus):
            request = _unpack(packed, pb.GetFEMBStatus())
            return _femb_status_reply(self, request.read_voltages).SerializeToString()

        if _is(packed, pb.ResetTiming):
            await self.reset_timing()
            return _timing_reply(self).SerializeToString()

        if _is(packed, pb.GetTimingStatus):
            return _timing_reply(self).SerializeToString()

        if _is(packed, pb.GetTimestamp):
            timestamp = self.firmware_timestamp
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
            return pb.GetSWVersion.Version(version=self.software_version).SerializeToString()

        if _is(packed, pb.Script):
            request = _unpack(packed, pb.Script())
            self.last_script = bytes(request.script)
            source = "file" if request.file else "inline"
            self.append_log(f"executed emulated {source} script\n")
            return pb.Status(success=True, extra=b"emulated script complete\n").SerializeToString()

        if _is(packed, pb.ReadDaqSpy):
            request = _unpack(packed, pb.ReadDaqSpy())
            if request.deframe:
                return pb.ReadDaqSpy.DeframedDaqSpy(
                    crate_num=0,
                    wib_num=0,
                    num_samples=0,
                    deframed_samples=b"",
                    deframed_timestamps=b"",
                    success=True,
                ).SerializeToString()
            return pb.ReadDaqSpy.DaqSpy(
                buf0=b"",
                buf1=b"",
                success=True,
            ).SerializeToString()

        if _is(packed, pb.LogControl):
            request = _unpack(packed, pb.LogControl())
            contents = self.boot_log if request.boot_log else bytes(self.log)
            if not request.return_log and not request.boot_log:
                contents = b""
            if request.clear_log:
                self.log.clear()
            return pb.LogControl.Log(contents=contents).SerializeToString()

        if _is(packed, pb.ConfigurePower):
            request = _unpack(packed, pb.ConfigurePower())
            self.power_configuration = {
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
            await self.apply_femb_power((request.femb0, request.femb1, request.femb2, request.femb3))
            return pb.Status(success=True, extra=b"emulated FEMB power transition\n").SerializeToString()

        if _is(packed, pb.ConfigureWIB):
            request = _unpack(packed, pb.ConfigureWIB())
            enabled = tuple(item.enabled for item in request.fembs[:4])
            enabled = enabled + (False,) * (4 - len(enabled))
            generation = await self.configure(enabled)
            return pb.Status(
                success=True, extra=f"emulated WIB configuration generation {generation}\n".encode()
            ).SerializeToString()

        if _is(packed, pb.Peek):
            request = _unpack(packed, pb.Peek())
            return pb.RegValue(addr=request.addr, value=self.registers.get(request.addr, 0)).SerializeToString()

        if _is(packed, pb.Poke):
            request = _unpack(packed, pb.Poke())
            self.registers[request.addr] = request.value
            return pb.RegValue(addr=request.addr, value=request.value).SerializeToString()

        if _is(packed, pb.CDPeek):
            request = _unpack(packed, pb.CDPeek())
            key = _coldata_key(request)
            return _coldata_reply(request, self.coldata_registers.get(key, 0)).SerializeToString()

        if _is(packed, pb.CDPoke):
            request = _unpack(packed, pb.CDPoke())
            self.coldata_registers[_coldata_key(request)] = request.data & 0xFF
            return _coldata_reply(request, request.data & 0xFF).SerializeToString()

        if _is(packed, pb.SetFakeTime):
            request = _unpack(packed, pb.SetFakeTime())
            self.fake_time = request.time
            return pb.Empty().SerializeToString()

        if any(
            _is(packed, message_type)
            for message_type in (pb.StartFakeTime, pb.CDFastCmd, pb.Calibrate, pb.Recompile)
        ):
            if _is(packed, pb.Calibrate) or _is(packed, pb.Recompile):
                return pb.Status(success=True, extra=b"emulated command complete\n").SerializeToString()
            return pb.Empty().SerializeToString()

        if _is(packed, pb.Reboot):
            self.timing_locked = False
            return pb.Empty().SerializeToString()

        if _is(packed, pb.Update):
            _unpack(packed, pb.Update())
            self.update_generation += 1
            self.append_log(
                f"accepted emulated update generation {self.update_generation}\n"
            )
            self.timing_locked = False
            return pb.Empty().SerializeToString()

        return b""


def _is(packed: object, message_type: type[Message]) -> bool:
    return packed.Is(message_type.DESCRIPTOR)  # type: ignore[attr-defined]


def _unpack(packed: object, message: Message) -> Message:
    if not packed.Unpack(message):  # type: ignore[attr-defined]
        raise DecodeError(f"could not unpack {message.DESCRIPTOR.full_name}")
    return message


def _sensor_reply(model: Wib) -> Message:
    sensors = pb.GetSensors.Sensors()
    sensors.ltc2990_4e_voltages.extend([5.0, 5.0, 1.2, 0.6])
    sensors.ltc2990_4c_voltages.extend([1.2, 1.2, 3.3, 3.3])
    sensors.ltc2991_48_voltages.extend([0.85, 0.85, 0.9, 0.9, 2.5, 2.5, 1.8, 1.8])
    sensors.ad7414_49_temp = model.sensors.get("ad7414_49_temp", 28.0)
    sensors.ad7414_4d_temp = model.sensors.get("ad7414_4d_temp", 29.0)
    sensors.ad7414_4a_temp = model.sensors.get("ad7414_4a_temp", 30.0)
    sensors.ltc2499_15_temps.extend([model.sensors.get(f"temperature_{index}", 27.0) for index in range(7)])
    if model.telemetry is not None:
        for index, name in enumerate(("ad7414_49_temp", "ad7414_4d_temp", "ad7414_4a_temp")):
            setattr(sensors, name, model.telemetry.analog(getattr(sensors, name), .5, index))
        for index, value in enumerate(sensors.ltc2499_15_temps):
            sensors.ltc2499_15_temps[index] = model.telemetry.analog(value, .5, index + 3)
        for group, name in enumerate(("ltc2990_4e_voltages", "ltc2990_4c_voltages", "ltc2991_48_voltages")):
            readings = getattr(sensors, name)
            for index, value in enumerate(readings):
                readings[index] = model.telemetry.analog(value, abs(value)*.005, 20+group*8+index)
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


def _femb_status_reply(model: Wib, read_voltages: bool) -> Message:
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


def _timing_reply(model: Wib) -> Message:
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
