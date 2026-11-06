"""A5202 slow controls through the CAEN FERSlib 2.2 C API.

Opening a connection uses FERS_OpenDevice, which stops acquisition and can
write calibration settings. Use this client only when it owns the board.
"""

import ctypes as ct
import math
import os
from ctypes.util import find_library
from dataclasses import dataclass
from ipaddress import IPv4Address
from threading import RLock

# FERSlib keeps board state and its last error in process-wide variables.
_LOCK = RLock()
_CONCENTRATORS = {}


class FersError(RuntimeError):
    """An SDK call failed, or returned an unusable sensor value."""

    def __init__(self, operation, code, detail):
        self.operation = operation
        self.code = code
        super().__init__(f"{operation} ({code}): {detail}")


class _BoardInfo(ct.Structure):
    """FERS_BoardInfo_t, with the C compiler's default alignment."""

    _fields_ = [
        ("pid", ct.c_uint32),
        ("fers_code", ct.c_uint16),
        ("pcb_revision", ct.c_uint8),
        ("model_code", ct.c_char * 16),
        ("model_name", ct.c_char * 16),
        ("form_factor", ct.c_uint8),
        ("channels", ct.c_uint16),
        ("fpga_firmware", ct.c_uint32),
        ("mcu_firmware", ct.c_uint32),
    ]


@dataclass(frozen=True)
class BoardInfo:
    """Board identity cached by FERSlib when the connection opens."""

    pid: int
    fers_code: int
    pcb_revision: int
    model_code: str
    model_name: str
    form_factor: int
    channels: int
    fpga_firmware: int
    mcu_firmware: int


@dataclass(frozen=True)
class HvStatus:
    """High voltage output state and fault flags read from the board."""

    enabled: bool
    ramping: bool
    overcurrent: bool
    overvoltage: bool


_FLOAT_READS = {
    "board_temperature_c": "FERS_Get_Board_Temp",
    "fpga_temperature_c": "FERS_Get_FPGA_Temp",
    "hv_temperature_c": "FERS_HV_Get_IntTemp",
    "detector_temperature_c": "FERS_HV_Get_DetectorTemp",
    "bias_voltage_v": "FERS_HV_Get_Vbias",
    "voltage_v": "FERS_HV_Get_Vmon",
    "current_limit_ma": "FERS_HV_Get_Imax",
    "current_ma": "FERS_HV_Get_Imon",
}


def _path_bytes(path):
    """Validate paths before passing them to the SDK's fixed buffers."""
    if not isinstance(path, str):
        raise TypeError("Use eth:<IPv4>[:tdl:<chain>:<node>] or usb:<PID or index>")
    parts = path.split(":")
    if len(parts) not in (2, 5):
        raise ValueError("Use eth:<IPv4>[:tdl:<chain>:<node>] or usb:<PID or index>")
    interface, address = parts[:2]
    if interface == "eth":
        IPv4Address(address)
    elif interface == "usb" and address.isascii() and address.isdecimal():
        if len(address) > 10 or int(address) > 0x7FFFFFFF:
            raise ValueError("USB PID or index must fit a signed 32-bit integer")
    else:
        raise ValueError("Use eth:<IPv4 address> or usb:<PID or index>")
    if len(parts) == 5:
        if interface != "eth" or parts[2] != "tdl":
            raise ValueError("Use eth:<concentrator IPv4>:tdl:<chain>:<node>")
        for value, maximum in zip(parts[3:], (7, 15), strict=True):
            if not value.isascii() or not value.isdecimal() or len(value) > 2 or int(value) > maximum:
                raise ValueError("TDlink chain must be 0–7 and node must be 0–15")
    return path.encode("ascii")


def _uint32(value):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Register addresses and values must be unsigned 32-bit integers")
    return value


def _bounded(value, minimum, maximum, unit):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Use a number between {minimum} and {maximum} {unit}")
    if not minimum <= value <= maximum:
        raise ValueError(f"Use a number between {minimum} and {maximum} {unit}")
    return value


def _load_library(path):
    name = path or os.environ.get("CAEN_FERSLIB_LIBRARY") or find_library("caenferslib")
    if not name:
        raise OSError("Install CAEN FERSlib or set CAEN_FERSLIB_LIBRARY to its shared library")
    lib = ct.CDLL(os.fspath(name))
    try:
        release = lib.FERS_GetLibReleaseNum
    except AttributeError as error:
        raise OSError(f"{name} does not provide FERS_GetLibReleaseNum") from error
    release.restype = ct.c_char_p
    release.argtypes = []
    version = (release() or b"").decode("ascii", errors="replace")
    if not version.startswith("2.2."):
        raise RuntimeError(f"FERSlib {version} is unsupported; this binding targets 2.2.x")
    signatures = {
        "FERS_GetLibReleaseNum": (ct.c_char_p, []),
        "FERS_GetLastError": (ct.c_int, [ct.POINTER(ct.c_char)]),
        "FERS_OpenDevice": (ct.c_int, [ct.c_char_p, ct.POINTER(ct.c_int)]),
        "FERS_CloseDevice": (ct.c_int, [ct.c_int]),
        "FERS_TDLchainsInitialized": (ct.c_bool, [ct.c_int]),
        "FERS_EnumTDLchains": (ct.c_int, [ct.c_int, ct.POINTER(ct.c_float * 16)]),
        "FERS_GetBoardInfo": (ct.c_int, [ct.c_int, ct.POINTER(_BoardInfo)]),
        "FERS_ReadRegister": (ct.c_int, [ct.c_int, ct.c_uint32, ct.POINTER(ct.c_uint32)]),
        "FERS_WriteRegister": (ct.c_int, [ct.c_int, ct.c_uint32, ct.c_uint32]),
        "FERS_HV_Get_Status": (ct.c_int, [ct.c_int] + [ct.POINTER(ct.c_int)] * 4),
        "FERS_HV_Set_OnOff": (ct.c_int, [ct.c_int, ct.c_int]),
        "FERS_HV_Set_Vbias": (ct.c_int, [ct.c_int, ct.c_float]),
        "FERS_HV_Set_Imax": (ct.c_int, [ct.c_int, ct.c_float]),
    }
    signatures.update({name: (ct.c_int, [ct.c_int, ct.POINTER(ct.c_float)])
                       for name in _FLOAT_READS.values()})
    for symbol, (result, arguments) in signatures.items():
        try:
            function = getattr(lib, symbol)
        except AttributeError as error:
            raise OSError(f"{name} does not provide {symbol}") from error
        function.restype = result
        function.argtypes = arguments
    return lib


class A5202:
    """One A5202/DT5202 over Ethernet, USB or a concentrator's TDlink.

    The native library loads on open(), so importing this module does not
    require FERSlib. Calls are synchronous and share a lock across instances.
    No HV setpoint or output state is changed automatically by this wrapper.
    """

    def __init__(self, path, *, library=None):
        self.path = path
        self._encoded_path = _path_bytes(path)
        self._library_path = library
        self._lib = None
        self._handle = None
        self._concentrator = None

    def _open_concentrator(self):
        path = self._encoded_path.split(b":tdl:", 1)[0] + b":cnc"
        key = (self._lib._handle, path)
        if key not in _CONCENTRATORS:
            handle = ct.c_int(-1)
            self._call("FERS_OpenDevice", path, ct.byref(handle))
            try:
                if not self._lib.FERS_TDLchainsInitialized(handle.value):
                    self._call("FERS_EnumTDLchains", handle.value, None)
            except BaseException:
                self._call("FERS_CloseDevice", handle.value)
                raise
            _CONCENTRATORS[key] = [handle.value, 0]
        _CONCENTRATORS[key][1] += 1
        self._concentrator = key

    def _call(self, name, *arguments):
        # Caller holds _LOCK through the call and retrieval of its error text.
        error = ct.create_string_buffer(1024)
        self._lib.FERS_GetLastError(error)  # discard any previous message
        code = getattr(self._lib, name)(*arguments)
        if code != 0:
            self._lib.FERS_GetLastError(error)
            raise FersError(name, code, error.value.decode("utf-8", errors="replace"))

    def _connected_handle(self):
        if self._handle is None:
            raise RuntimeError("A5202 connection is closed; call open() first")
        return self._handle

    def open(self):
        """Open and identify the board. FERSlib stops any active acquisition."""
        with _LOCK:
            if self._handle is not None:
                return self
            if self._lib is None:
                self._lib = _load_library(self._library_path)
            try:
                if b":tdl:" in self._encoded_path and self._concentrator is None:
                    self._open_concentrator()
                handle = ct.c_int(-1)
                self._call("FERS_OpenDevice", self._encoded_path, ct.byref(handle))
                self._handle = handle.value
                info = self.board_info()
                if info.fers_code != 5202:
                    raise ValueError(f"Expected a 5202 board, found {info.fers_code}")
            except BaseException:
                self.close()
                raise
            return self

    def close(self):
        """Release the connection; leave the HV output at its current setting."""
        with _LOCK:
            if self._handle is not None:
                self._call("FERS_CloseDevice", self._handle)
                self._handle = None
            if self._concentrator is not None:
                handle, users = _CONCENTRATORS[self._concentrator]
                if users == 1:
                    self._call("FERS_CloseDevice", handle)
                    del _CONCENTRATORS[self._concentrator]
                else:
                    _CONCENTRATORS[self._concentrator][1] -= 1
                self._concentrator = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_exception):
        self.close()

    @property
    def library_version(self):
        """The loaded FERSlib release string."""
        with _LOCK:
            self._connected_handle()
            return self._lib.FERS_GetLibReleaseNum().decode("ascii")

    def board_info(self):
        """Return identity and firmware revisions recorded at connection time."""
        with _LOCK:
            info = _BoardInfo()
            self._call("FERS_GetBoardInfo", self._connected_handle(), ct.byref(info))
            values = {name: getattr(info, name) for name, _ in info._fields_}
            for name in ("model_name", "model_code"):
                values[name] = values[name].decode("ascii", errors="replace")
            return BoardInfo(**values)

    def read_register(self, address):
        """Read an unsigned 32-bit register using the board's register map."""
        address = _uint32(address)
        with _LOCK:
            value = ct.c_uint32()
            self._call("FERS_ReadRegister", self._connected_handle(), address, ct.byref(value))
            return value.value

    def write_register(self, address, value):
        """Write an unsigned 32-bit register immediately."""
        address, value = _uint32(address), _uint32(value)
        with _LOCK:
            self._call("FERS_WriteRegister", self._connected_handle(), address, value)

    def read(self, quantity):
        """Read a named quantity in V, mA or degrees C (see _FLOAT_READS)."""
        if quantity not in _FLOAT_READS:
            raise ValueError(f"Unknown quantity {quantity!r}; choose from {', '.join(_FLOAT_READS)}")
        name = _FLOAT_READS[quantity]
        with _LOCK:
            value = ct.c_float()
            self._call(name, self._connected_handle(), ct.byref(value))
            if not math.isfinite(value.value) or value.value == 999:
                raise FersError(name, None, "Invalid sensor reading")
            return value.value

    def hv_status(self):
        """Read HV on/off, ramping, overcurrent and overvoltage flags."""
        with _LOCK:
            flags = [ct.c_int() for _ in range(4)]
            self._call("FERS_HV_Get_Status", self._connected_handle(),
                       *(ct.byref(flag) for flag in flags))
            return HvStatus(*(bool(flag.value) for flag in flags))

    def set_bias_voltage(self, volts):
        """Set the common bias voltage, within the A5202's 20–85 V range."""
        volts = _bounded(volts, 20, 85, "V")
        with _LOCK:
            self._call("FERS_HV_Set_Vbias", self._connected_handle(), volts)

    def set_current_limit(self, milliamps):
        """Set the common HV current limit, from 0 to 10 mA."""
        milliamps = _bounded(milliamps, 0, 10, "mA")
        with _LOCK:
            self._call("FERS_HV_Set_Imax", self._connected_handle(), milliamps)

    def set_hv_enabled(self, enabled):
        """Switch the common HV output; enabled must be a bool."""
        if type(enabled) is not bool:
            raise ValueError("HV enabled must be True or False")
        with _LOCK:
            self._call("FERS_HV_Set_OnOff", self._connected_handle(), int(enabled))
