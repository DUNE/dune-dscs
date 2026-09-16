"""Config-driven IPMI, SNMP and SCPI sensor readers.

Each reader is built from one entry of devices.yaml and exposes a
synchronous `.read()` returning {sensor_name: value} for exactly the
sensors listed in that entry - nothing here needs to change when sensors
are added, only the config.
"""
import asyncio
import socket

import pyipmi
import pyipmi.interfaces
import pyipmi.sdr

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd,
)


class IPMIReader:
    """Reads named sensors from a BMC over IPMI-over-LAN (RMCP+)."""

    def __init__(self, host, port=623, username="", password="",
                 priv_level="administrator", sensors=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.priv_level = priv_level
        self.sensor_names = list(sensors or [])
        self._ipmi = None
        self._sdr_by_name = {}

    def connect(self):
        interface = pyipmi.interfaces.create_interface("rmcp")
        ipmi = pyipmi.create_connection(interface)
        ipmi.target = pyipmi.Target(0x20)
        ipmi.session.set_session_type_rmcp(self.host, self.port)
        ipmi.session.set_auth_type_user(self.username, self.password)
        ipmi.session.set_priv_level(self.priv_level)
        ipmi.open()

        wanted = set(self.sensor_names)
        sdr_by_name = {}
        for record in ipmi.device_sdr_entries():
            if record.type != pyipmi.sdr.SDR_TYPE_FULL_SENSOR_RECORD:
                continue
            if record.device_id_string in wanted:
                sdr_by_name[record.device_id_string] = record

        for name in wanted - sdr_by_name.keys():
            print(f" [!] IPMI sensor '{name}' not found in SDR on {self.host}")

        self._ipmi = ipmi
        self._sdr_by_name = sdr_by_name

    def close(self):
        if self._ipmi is not None:
            try:
                self._ipmi.close()
            except Exception:
                pass
        self._ipmi = None
        self._sdr_by_name = {}

    def read(self):
        """Return {sensor_name: value}. Connects/reconnects as needed."""
        if self._ipmi is None:
            try:
                self.connect()
            except Exception as e:
                print(f" [!] IPMI connect failed for {self.host}: {e}")
                return {}

        values = {}
        try:
            for name, record in self._sdr_by_name.items():
                raw, _states = self._ipmi.get_sensor_reading(record.number, record.owner_lun)
                value = record.convert_sensor_raw_to_value(raw)
                if value is not None:
                    values[name] = float(value)
        except Exception as e:
            print(f" [!] IPMI read error on {self.host}: {e}")
            self.close()

        return values


class SNMPReader:
    """Reads named OIDs from an SNMP agent (v1/v2c, community-based)."""

    def __init__(self, host, port=161, community="public", version="2c", sensors=None):
        self.host = host
        self.port = port
        self.community = community
        self.mp_model = 0 if str(version) == "1" else 1
        self.sensors = list(sensors or [])  # [{"name": ..., "oid": ...}, ...]

    def read(self):
        """Return {sensor_name: value}."""
        return asyncio.run(self._read_async())

    async def _read_async(self):
        # A fresh SnmpEngine is required per event loop - pysnmp's engine
        # binds to the loop it was created on, so reusing one across
        # separate asyncio.run() calls hangs on the second call.
        engine = SnmpEngine()
        values = {}

        try:
            target = await UdpTransportTarget.create((self.host, self.port), timeout=2, retries=1)
        except Exception as e:
            print(f" [!] SNMP target error for {self.host}: {e}")
            return values

        for sensor in self.sensors:
            name = sensor["name"]
            oid = sensor["oid"]
            try:
                error_indication, error_status, _error_index, var_binds = await get_cmd(
                    engine,
                    CommunityData(self.community, mpModel=self.mp_model),
                    target,
                    ContextData(),
                    ObjectType(ObjectIdentity(oid)),
                )
            except Exception as e:
                print(f" [!] SNMP read error for {self.host}/{name}: {e}")
                continue

            if error_indication:
                print(f" [!] SNMP error for {self.host}/{name}: {error_indication}")
                continue
            if error_status:
                print(f" [!] SNMP error for {self.host}/{name}: {error_status.prettyPrint()}")
                continue

            for _oid, val in var_binds:
                try:
                    values[name] = float(val)
                except (TypeError, ValueError):
                    values[name] = str(val)

        return values


class SCPIReader:
    """Reads named measurements from a SCPI-over-TCP ("SCPI-RAW") instrument.

    Each sensor is a literal SCPI query string (e.g. "MEAS:VOLT:DC?"); the
    instrument's ASCII reply is parsed as a float. Keeps one persistent TCP
    connection open across reads, like a real instrument session, and
    reconnects lazily on error.
    """

    def __init__(self, host, port=5025, timeout=2.0, sensors=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sensors = list(sensors or [])  # [{"name": ..., "command": ...}, ...]
        self._sock = None
        self._buf = b""

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._buf = b""

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._buf = b""

    def _readline(self):
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed by instrument")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("ascii", errors="replace").strip()

    def _query(self, command):
        self._sock.sendall(command.encode("ascii") + b"\n")
        return self._readline()

    def read(self):
        """Return {sensor_name: value}. Connects/reconnects as needed."""
        if self._sock is None:
            try:
                self.connect()
            except Exception as e:
                print(f" [!] SCPI connect failed for {self.host}: {e}")
                return {}

        values = {}
        try:
            for sensor in self.sensors:
                name = sensor["name"]
                command = sensor["command"]
                reply = self._query(command)
                try:
                    values[name] = float(reply)
                except ValueError:
                    print(f" [!] SCPI non-numeric reply for {self.host}/{name}: {reply!r}")
        except Exception as e:
            print(f" [!] SCPI read error on {self.host}: {e}")
            self.close()

        return values
