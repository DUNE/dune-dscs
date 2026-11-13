"""Native readers. Each returns {configured source: scalar value}."""

import asyncio

import zmq
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    UdpTransportTarget,
    get_cmd,
)
from pysnmp.proto import errind
from pysnmp.proto.api import v2c

from .emulator.protocols._generated import daphneV3_high_level_confs_pb2 as daphne
from .emulator.protocols._generated import wib_pb2 as wib

WIB_READS = {
    "sensors": (wib.GetSensors, wib.GetSensors.Sensors),
    "femb": (wib.GetFEMBStatus, wib.GetFEMBStatus.FEMBStatus),
    "timing": (wib.GetTimingStatus, wib.GetTimingStatus.TimingStatus),
    "version": (wib.GetSWVersion, wib.GetSWVersion.Version),
}
DAPHNE_READS = {
    "info": (daphne.MT2_READ_GENERAL_INFO_REQ, daphne.InfoRequest, daphne.GeneralInfo),
    "counters": (daphne.MT2_READ_TRIGGER_COUNTERS_REQ,
                 daphne.ReadTriggerCountersRequest, daphne.ReadTriggerCountersResponse),
    "test_register": (daphne.MT2_READ_TEST_REG_REQ, daphne.TestRegRequest, daphne.TestRegResponse),
}


def field(message, path):
    for part in path.split("."):
        message = message[int(part)] if part.isdecimal() else getattr(message, part)
    return message


class BoardClient:
    def __init__(self, kind, endpoint, context):
        self.kind, self.endpoint, self.context = kind, endpoint, context
        self.socket = None
        self.sequence = 0

    async def close(self):
        if self.socket is not None:
            self.socket.close(linger=0)
            self.socket = None

    async def exchange(self, payload):
        if self.socket is None:
            self.socket = self.context.socket(zmq.REQ if self.kind == "wib" else zmq.DEALER)
            self.socket.setsockopt(zmq.LINGER, 0)
            self.socket.connect(self.endpoint)
        await self.socket.send(payload)
        return await self.socket.recv()

    async def read(self, sources):
        messages = {}
        try:
            # Read each protobuf group once, even when several variables use it.
            for group in dict.fromkeys(source.split(".", 1)[0] for source in sources):
                if self.kind == "wib":
                    request_type, response_type = WIB_READS[group]
                    command = wib.Command()
                    command.cmd.Pack(request_type())
                    message = response_type.FromString(await self.exchange(command.SerializeToString()))
                    if group == "sensors" and len(message.ltc2990_4e_voltages) != 4:
                        raise ValueError("invalid WIB sensor reply")
                    if group == "femb" and len(message.femb_power) != 4:
                        raise ValueError("invalid WIB power reply")
                else:
                    message_type, request_type, response_type = DAPHNE_READS[group]
                    self.sequence += 1
                    request = daphne.ControlEnvelopeV2(version=2, dir=daphne.DIR_REQUEST,
                        type=message_type, msg_id=self.sequence, payload=request_type().SerializeToString())
                    envelope = daphne.ControlEnvelopeV2.FromString(
                        await self.exchange(request.SerializeToString()))
                    if (envelope.version, envelope.dir, envelope.type, envelope.correl_id,
                        envelope.task_id, envelope.route) != (
                            2, daphne.DIR_RESPONSE, message_type + 1, self.sequence, 0, ""):
                        raise ValueError("DAPHNE reply does not match its request")
                    message = response_type.FromString(envelope.payload)
                    if group == "counters" and not message.success:
                        raise ValueError("DAPHNE counter read failed")
                messages[group] = message
            return {source: field(messages[source.split(".", 1)[0]], source.split(".", 1)[1])
                    for source in sources}
        except (Exception, asyncio.CancelledError):
            # Discard late replies and reset REQ's send/receive state after a timeout.
            await self.close()
            raise


class PduClient:
    def __init__(self, host, port, community, engine, timeout):
        self.host, self.port, self.community = host, port, community
        self.engine, self.timeout = engine, timeout
        self.target = None

    async def close(self):
        self.target = None

    async def read(self, sources):
        sources = list(dict.fromkeys(sources))
        if self.target is None:
            self.target = await UdpTransportTarget.create(
                (self.host, self.port), timeout=self.timeout, retries=0)
        values = {}
        # Bound UDP response size when a PDU exposes hundreds of monitoring objects.
        for start in range(0, len(sources), 10):
            chunk = sources[start:start + 10]
            values.update(await self._read_chunk(chunk))
        return values

    async def _read_chunk(self, sources):
        indication, status, _, bindings = await get_cmd(
            self.engine, CommunityData(self.community, mpModel=1), self.target, ContextData(),
            *(ObjectType(ObjectIdentity(source)) for source in sources), lookupMib=False)
        if isinstance(indication, errind.RequestTimedOut):
            raise TimeoutError(str(indication))
        if indication is not None or status:
            raise ConnectionError(str(indication or status))
        if len(bindings) != len(sources):
            raise ValueError("incomplete SNMP reply")
        values = {}
        for source, (oid, value) in zip(sources, bindings):
            if tuple(oid) != tuple(int(part) for part in source.split(".")):
                raise ValueError("SNMP reply has a different OID")
            if isinstance(value, (v2c.NoSuchObject, v2c.NoSuchInstance, v2c.EndOfMibView)):
                raise TypeError(f"SNMP object is unavailable: {source}")
            values[source] = value.asOctets().decode() if isinstance(value, v2c.OctetString) else int(value)
        return values
