import asyncio
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import zmq.asyncio
from pyasn1.codec.ber.encoder import encode
from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
from pysnmp.proto.api import v2c

from dune_dscs.bridge_clients import BoardClient, PduClient
from dune_dscs.emulator.__main__ import run
from dune_dscs.emulator.pdu import ROOT, PduAgent, TimedUdpTransport
from dune_dscs.emulator.timing import Timing


def port(udp=False):
    with socket.socket(type=socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class TimingTests(unittest.IsolatedAsyncioTestCase):
    def test_profiles_validate_and_repeat_samples(self):
        timing = Timing({'read': [10, 20]})
        self.assertEqual([timing.seconds('read') for _ in range(3)], [.01, .02, .01])
        self.assertEqual(timing.seconds('unmodelled'), 0)
        for values in ([], [-1], [True], ['1'], [float('nan')], [float('inf')]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Timing({'read': values})
        examples = Path(__file__).parents[1] / 'examples/timing'
        for kind, name in [('wib', 'wib-source-estimate'), ('daphne', 'daphne15-measured'),
                           ('pdu', 'pdu-measured')]:
            self.assertTrue(Timing.load(examples / (name + '.json'), kind).samples)
            with self.assertRaises(ValueError):
                Timing.load(examples / (name + '.json'), 'other')

    async def test_delayed_board_reads_leave_the_event_loop_running(self):
        cases = [('wib', 'GetSensors', 'sensors.ad7414_49_temp', 28.0),
                 ('daphne', 'MT2_READ_TEST_REG_REQ', 'test_register.value', 0xDEADBEEF)]
        for kind, operation, source, expected in cases:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'timing.json'
                path.write_text(json.dumps({'kind': kind, 'delays_ms': {operation: [60]}}))
                endpoint_port = port()
                task = asyncio.create_task(run(SimpleNamespace(
                    kind=kind, host='127.0.0.1', port=endpoint_port, timing=path)))
                context = zmq.asyncio.Context()
                client = BoardClient(kind, f'tcp://127.0.0.1:{endpoint_port}', context)
                try:
                    await asyncio.sleep(.02)
                    start = time.monotonic()
                    read = asyncio.create_task(client.read([source]))
                    ticks = 0
                    while not read.done():
                        await asyncio.sleep(.005)
                        ticks += 1
                        if time.monotonic() - start > 3:
                            self.fail('Native read did not finish')
                    self.assertEqual((await read)[source], expected)
                    self.assertGreaterEqual(time.monotonic() - start, .06)
                    self.assertGreater(ticks, 2)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await client.close()
                    context.term()

    async def test_snmp_delay_preserves_native_readback(self):
        agent = PduAgent('127.0.0.1', port(True), timing=Timing({'GetRequestPDU:1': [60]}))
        engine = SnmpEngine()
        await agent.start()
        try:
            client = PduClient('127.0.0.1', agent.port, 'private', engine, 1)
            source = '.'.join(map(str, ROOT + (3, 2, 2, 1, 4, 1)))
            start = time.monotonic()
            self.assertEqual((await client.read([source]))[source], 10)
            self.assertGreaterEqual(time.monotonic() - start, .06)
        finally:
            engine.close_dispatcher()
            await agent.close()

    async def test_snmp_pending_delays_are_bounded_and_cancelled(self):
        transport = TimedUdpTransport(Timing({'GetRequestPDU:1': [60000]}))
        message, request = v2c.Message(), v2c.GetRequestPDU()
        v2c.apiMessage.set_defaults(message)
        v2c.apiPDU.set_defaults(request)
        v2c.apiPDU.set_varbinds(request, [(ROOT, v2c.Null(''))])
        v2c.apiMessage.set_pdu(message, request)
        for _ in range(80):
            transport.datagram_received(encode(message), ('127.0.0.1', 1))
        handles = list(transport.pending)
        self.assertEqual(len(handles), 64)
        transport.close_transport()
        self.assertTrue(all(handle.cancelled() for handle in handles))
        self.assertFalse(transport.pending)
