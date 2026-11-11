"""Read native devices and publish a common, read-only OPC UA view."""

import argparse
import asyncio
import logging
import math
import re
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
import zmq.asyncio
from asyncua import Server, ua
from google.protobuf.message import DecodeError
from pysnmp.hlapi.v3arch.asyncio import SnmpEngine

from .bridge_clients import DAPHNE_READS, WIB_READS, BoardClient, PduClient

LOG = logging.getLogger(__name__)
NAMESPACE = "urn:dune:dscs:bridge"
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
TYPES = {name: ua.VariantType[name] for name in
         ("Boolean", "Int32", "UInt32", "Int64", "UInt64", "Double", "String")}
RESERVED = {"Technology", "Endpoint", "Available", "Sequence", "LastSuccess", "LastError"}


@dataclass
class Variable:
    source: str
    type: str = "Double"
    unit: str = ""
    values: dict = field(default_factory=dict)

    def convert(self, value):
        if self.values:
            value = self.values[value]
        if self.type == "Boolean":
            if type(value) is not bool:
                raise ValueError("Boolean variables need a boolean or a values mapping")
        elif self.type == "String":
            if not isinstance(value, str):
                raise ValueError("String variable received a non-string value")
        elif self.type == "Double":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Double variable received a non-finite number or a different type")
            value = float(value)
        else:
            bits = 32 if self.type.endswith("32") else 64
            lower = 0 if self.type.startswith("U") else -(2 ** (bits - 1))
            upper = 2 ** bits - 1 if lower == 0 else 2 ** (bits - 1) - 1
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"value is outside {self.type}")
        return value


@dataclass
class Device:
    id: str
    kind: str
    endpoint: str
    variables: dict[str, Variable]
    community: str = "private"
    period: float = 1.0


@dataclass
class Config:
    devices: list[Device]
    endpoint: str = "opc.tcp://127.0.0.1:4840/dune/"
    namespace: str = NAMESPACE
    timeout: float = 2.0
    concurrency: int = 32


def load_config(path, kinds=None):
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise TypeError("configuration must be a mapping")
    devices = []
    for entry in data.pop("devices", []):
        entry = dict(entry)
        entry["variables"] = {name: Variable(**settings) for name, settings in entry["variables"].items()}
        devices.append(Device(**entry))
    config = Config(devices=devices, **data)
    validate(config)
    if kinds:
        config.devices = [device for device in devices if device.kind in kinds]
        if not config.devices:
            raise ValueError("no devices match --kind")
    return config


def validate(config):
    if not config.devices or len({d.id for d in config.devices}) != len(config.devices):
        raise ValueError("devices must be non-empty and have unique IDs")
    if type(config.concurrency) is not int or config.concurrency < 1:
        raise ValueError("concurrency must be a positive integer")
    if not math.isfinite(config.timeout) or config.timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    endpoint = urlsplit(config.endpoint)
    if endpoint.scheme != "opc.tcp" or not endpoint.hostname or not endpoint.port or not config.namespace:
        raise ValueError("an opc.tcp://host:port endpoint and namespace are required")
    for device in config.devices:
        if not NAME.fullmatch(device.id) or device.kind not in ("wib", "daphne", "pdu"):
            raise ValueError("device IDs need simple names; kinds are wib, daphne or pdu")
        endpoint = urlsplit(device.endpoint)
        scheme = "udp" if device.kind == "pdu" else "tcp"
        if (endpoint.scheme != scheme or not endpoint.hostname or not endpoint.port
                or endpoint.path or endpoint.query or endpoint.fragment or endpoint.username):
            raise ValueError(f"{device.id}: expected {scheme}://host:port")
        if not math.isfinite(device.period) or device.period <= 0 or not device.variables:
            raise ValueError(f"{device.id}: period must be positive; variables cannot be empty")
        for name, variable in device.variables.items():
            if not NAME.fullmatch(name) or name in RESERVED or variable.type not in TYPES:
                raise ValueError(f"{device.id}: invalid variable name or type: {name}")
            if device.kind == "pdu":
                if not re.fullmatch(r"\d+(\.\d+)+", variable.source):
                    raise ValueError(f"{device.id}.{name}: source must be a numeric OID")
            else:
                reads = WIB_READS if device.kind == "wib" else DAPHNE_READS
                group, separator, path = variable.source.partition(".")
                if group not in reads or not separator or not path:
                    raise ValueError(f"{device.id}.{name}: unknown protobuf source")


class Bridge:
    def __init__(self, config):
        validate(config)
        self.config = config
        self.server = Server()
        self.clients, self.nodes = {}, {}
        self.tasks = []
        self.context = None
        self.snmp = None
        self._started = False

    async def start(self):
        if self._started:
            raise RuntimeError("bridge is already started")
        self._started = True
        try:
            self.context = zmq.asyncio.Context()
            if any(d.kind == "pdu" for d in self.config.devices):
                self.snmp = SnmpEngine()
            await self.server.init()
            self.server.set_endpoint(self.config.endpoint)
            self.server.set_server_name("DUNE slow controls bridge")
            self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
            await self.server.set_application_uri(self.config.namespace)
            index = await self.server.register_namespace(self.config.namespace)
            root = await self.server.nodes.objects.add_folder(ua.NodeId("Devices", index), "Devices")
            for device in self.config.devices:
                folder = await root.add_folder(ua.NodeId(f"Devices.{device.id}", index), device.id)
                nodes = self.nodes[device.id] = {}
                common = [("Technology", device.kind, ua.VariantType.String),
                          ("Endpoint", device.endpoint, ua.VariantType.String),
                          ("Available", False, ua.VariantType.Boolean),
                          ("Sequence", 0, ua.VariantType.UInt64),
                          ("LastSuccess", datetime(1970, 1, 1, tzinfo=timezone.utc), ua.VariantType.DateTime),
                          ("LastError", "waiting for first read", ua.VariantType.String)]
                for name, value, variant in common:
                    nodes[name] = await folder.add_variable(
                        ua.NodeId(f"Devices.{device.id}.{name}", index), name, value, variant)
                for name, variable in device.variables.items():
                    initial = False if variable.type == "Boolean" else "" if variable.type == "String" else 0
                    node = nodes[name] = await folder.add_variable(
                        ua.NodeId(f"Devices.{device.id}.{name}", index), name, initial, TYPES[variable.type])
                    await node.add_property(ua.NodeId(f"Devices.{device.id}.{name}.Unit", index),
                                            "Unit", variable.unit)
                    await node.write_value(ua.DataValue(
                        ua.Variant(initial, TYPES[variable.type]),
                        StatusCode=ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData)))
                endpoint = urlsplit(device.endpoint)
                self.clients[device.id] = PduClient(endpoint.hostname, endpoint.port, device.community,
                    self.snmp, self.config.timeout) if device.kind == "pdu" else BoardClient(
                        device.kind, device.endpoint, self.context)
            await self.server.start()
            limiter = asyncio.Semaphore(self.config.concurrency)
            self.tasks = [asyncio.create_task(self._poll(device, limiter), name=f"poll:{device.id}")
                          for device in self.config.devices]
        except BaseException:
            await self.close()
            raise

    async def close(self):
        if not self._started:
            return
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        await asyncio.gather(*(client.close() for client in self.clients.values()))
        self.clients.clear()
        if self.snmp is not None:
            self.snmp.close_dispatcher()
            self.snmp = None
        if self.context is not None:
            self.context.term()
            self.context = None
        await self.server.stop()
        self.nodes.clear()
        self._started = False

    async def _poll(self, device, limiter):
        nodes = self.nodes[device.id]
        client = self.clients[device.id]
        values = {name: False if variable.type == "Boolean" else "" if variable.type == "String" else 0
                  for name, variable in device.variables.items()}
        last_success, sequence = None, 0
        was_available = False
        while True:
            started = asyncio.get_running_loop().time()
            try:
                async with limiter:
                    readings = await asyncio.wait_for(
                        client.read([v.source for v in device.variables.values()]), self.config.timeout)
                converted = {name: variable.convert(readings[variable.source])
                             for name, variable in device.variables.items()}
                last_success = datetime.now(timezone.utc)
                values, sequence = converted, sequence + 1
                code, error = ua.StatusCodes.Good, ""
            except Exception as exc:  # noqa: BLE001 - isolate failures to this device.
                code = ua.StatusCodes.BadDecodingError if isinstance(exc, (
                    ValueError, TypeError, LookupError, AttributeError, DecodeError)) else ua.StatusCodes.BadNoCommunication
                error = f"{type(exc).__name__}: {exc}"[:300]
            available = code == ua.StatusCodes.Good
            if available != was_available:
                LOG.info("%s: %s", device.id, "available" if available else error)
            was_available = available
            for name, variable in device.variables.items():
                # Keep the last successful sample time when communication fails.
                await nodes[name].write_value(ua.DataValue(
                    ua.Variant(values[name], TYPES[variable.type]),
                    StatusCode=ua.StatusCode(code), SourceTimestamp=last_success))
            await nodes["Available"].write_value(available)
            await nodes["LastError"].write_value(error)
            if available:
                await nodes["LastSuccess"].write_value(last_success)
                await nodes["Sequence"].write_value(ua.Variant(sequence, ua.VariantType.UInt64))
            elapsed = asyncio.get_running_loop().time() - started
            # One task per device prevents overlapping polls and unbounded queues.
            await asyncio.sleep(max(0.01, device.period - elapsed))


async def run(config):
    bridge = Bridge(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    stopped = None
    try:
        await bridge.start()
        print(f"OPC UA bridge listening on {config.endpoint} ({len(config.devices)} devices)", flush=True)
        stopped = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([stopped, *bridge.tasks], return_when=asyncio.FIRST_COMPLETED)
        for task in done - {stopped}:
            task.result()  # Surface unexpected polling-task failures instead of serving frozen values.
            raise RuntimeError(f"polling task stopped: {task.get_name()}")
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        if stopped is not None:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)
        await bridge.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--kind", action="append", choices=("wib", "daphne", "pdu"))
    parser.add_argument("--endpoint", help="override the OPC UA endpoint")
    args = parser.parse_args()
    try:
        config = load_config(args.config, args.kind)
        if args.endpoint:
            config.endpoint = args.endpoint
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run(config))
    except KeyboardInterrupt:
        pass
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

