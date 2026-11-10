"""Small Raritan PDU2-MIB SNMP v2c emulator (pduId=1)."""

from pyasn1.codec.ber.decoder import decode
from pyasn1.error import PyAsn1Error
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto.api import v2c
from pysnmp.smi import error, instrum

ROOT = (1, 3, 6, 1, 4, 1, 13742, 6)
SWITCH = ROOT + (4, 1, 2, 1)
SENSOR_CONFIG = ROOT + (3, 5, 4, 1)
SENSOR_MEASUREMENT = ROOT + (5, 4, 3, 1)


class TimedUdpTransport(udp.UdpTransport):
    """Delay native requests; discard excess UDP traffic instead of growing a queue."""

    def __init__(self, timing):
        super().__init__()
        self.timing, self.pending = timing, set()

    def datagram_received(self, datagram, address):
        try:
            message, _ = decode(datagram, asn1Spec=v2c.Message())
            request = v2c.apiMessage.get_pdu(message)
            operation = f"{request.__class__.__name__}:{len(v2c.apiPDU.get_varbinds(request))}"
        except PyAsn1Error:
            return super().datagram_received(datagram, address)
        delay = self.timing.seconds(operation)
        if not delay:
            return super().datagram_received(datagram, address)
        if len(self.pending) >= 64:
            return

        def deliver():
            self.pending.discard(handle)
            super(TimedUdpTransport, self).datagram_received(datagram, address)

        handle = self.loop.call_later(delay, deliver)
        self.pending.add(handle)

    def close_transport(self):
        for handle in self.pending:
            handle.cancel()
        self.pending.clear()
        super().close_transport()


class Pdu(instrum.AbstractMibInstrumController):
    """Independent outlet state; all outlets start off."""

    def __init__(self, outlets=10, telemetry=None):
        if not 1 <= outlets <= 256:
            raise ValueError("outlets must be between 1 and 256")
        self.outlets = {index: False for index in range(1, outlets + 1)}
        self.telemetry = telemetry

    def _values(self):
        values = {
            (1, 3, 6, 1, 2, 1, 1, 1, 0): v2c.OctetString("Raritan PDU emulator"),
            ROOT + (3, 1, 0): v2c.Integer32(1),
            ROOT + (3, 2, 2, 1, 4, 1): v2c.Integer32(len(self.outlets)),
        }
        for outlet, enabled in self.outlets.items():
            values[SWITCH + (2, 1, outlet)] = v2c.Integer32(int(enabled))
            values[SWITCH + (3, 1, outlet)] = v2c.Integer32(7 if enabled else 8)
            values[ROOT + (3, 5, 3, 1, 3, 1, outlet)] = v2c.OctetString(f"Outlet {outlet}")
            # PDU2-MIB: current=1, voltage=4; readings use three decimal digits.
            for sensor, unit, nominal, amplitude in ((1, 2, .35, .05), (4, 1, 120, .5)):
                index = (1, outlet, sensor)
                reading = nominal if self.telemetry is None else self.telemetry.analog(
                    nominal, amplitude, outlet * 2 + sensor)
                values[SENSOR_CONFIG + (6,) + index] = v2c.Integer32(unit)
                values[SENSOR_CONFIG + (7,) + index] = v2c.Unsigned32(3)
                values[SENSOR_MEASUREMENT + (2,) + index] = v2c.Integer32(1)
                values[SENSOR_MEASUREMENT + (3,) + index] = v2c.Integer32(4)
                values[SENSOR_MEASUREMENT + (4,) + index] = v2c.Unsigned32(round(reading * 1000) if enabled else 0)
        return values

    def read_variables(self, *bindings, **_context):
        values = self._values()
        return [(name, values.get(tuple(name), v2c.NoSuchInstance())) for name, _ in bindings]

    def read_next_variables(self, *bindings, **_context):
        values = self._values()
        result = []
        for name, _ in bindings:
            successor = next((oid for oid in sorted(values) if oid > tuple(name)), None)
            result.append((v2c.ObjectIdentifier(successor), values[successor]) if successor
                          else (name, v2c.EndOfMibView()))
        return result

    def write_variables(self, *bindings, **_context):
        # Validate the whole SET before changing any outlet.
        operations = []
        for index, (name, value) in enumerate(bindings):
            oid = tuple(name)
            if oid[:-1] != SWITCH + (2, 1) or oid[-1] not in self.outlets:
                raise error.NotWritableError(idx=index)
            if not isinstance(value, v2c.Integer32):
                raise error.WrongTypeError(idx=index)
            if int(value) not in (0, 1):
                raise error.WrongValueError(idx=index)
            operations.append((oid[-1], bool(value)))
        for outlet, enabled in operations:
            self.outlets[outlet] = enabled
        return list(bindings)


class PduAgent:
    """One UDP listener exposing a PDU."""

    def __init__(self, host, port, outlets=10, community="private", timing=None, telemetry=None):
        self.host, self.port, self.community = host, port, community
        self.model = Pdu(outlets, telemetry=telemetry)
        self.engine = None
        self.responders = ()
        self.timing = timing

    async def start(self):
        self.engine = agent = engine.SnmpEngine()
        transport = (TimedUdpTransport(self.timing) if self.timing is not None
                     else udp.UdpTransport()).open_server_mode((self.host, self.port))
        config.add_transport(agent, udp.DOMAIN_NAME, transport)
        config.add_v1_system(agent, "emulator", self.community)
        config.add_vacm_user(agent, 2, "emulator", "noAuthNoPriv", (1, 3, 6), SWITCH + (2,))
        snmp_context = context.SnmpContext(agent)
        snmp_context.unregister_context_name("")
        snmp_context.register_context_name("", self.model)
        self.responders = tuple(responder(agent, snmp_context) for responder in (
            cmdrsp.GetCommandResponder, cmdrsp.SetCommandResponder,
            cmdrsp.NextCommandResponder, cmdrsp.BulkCommandResponder,
        ))
        await transport._lport  # Wait for the asyncio UDP bind to finish.

    async def close(self):
        if self.engine is not None:
            self.engine.close_dispatcher()
            self.engine = None
        self.responders = ()
