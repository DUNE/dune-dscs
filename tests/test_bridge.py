import asyncio
import json
import os
import socket
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from asyncua import Client, ua
from pysnmp.proto.api import v2c

from dune_dscs.bridge import (
    NAMESPACE,
    Bridge,
    Config,
    Device,
    Variable,
    load_config,
    validate,
)
from dune_dscs.emulator.__main__ import run as run_emulator
from dune_dscs.emulator.pdu import SWITCH, PduAgent
from dune_dscs.measure import measure


def free_port(udp=False):
    with socket.socket(type=socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def eventually(check):
    async def wait():
        while not await check():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(wait(), 8)


class ConfigTests(unittest.TestCase):
    def test_example_supports_mixed_or_single_technology(self):
        path = Path(__file__).parents[1] / 'examples/bridge.yaml'
        self.assertEqual([d.kind for d in load_config(path).devices], ['wib', 'daphne', 'pdu'])
        self.assertEqual([d.kind for d in load_config(path, ['wib']).devices], ['wib'])
        self.assertEqual(len(load_config(path, ['wib', 'pdu']).devices), 2)

    def test_invalid_configuration(self):
        good = Config([Device('wib-1', 'wib', 'tcp://127.0.0.1:1234',
                              {'Temperature': Variable('sensors.ad7414_49_temp')})])
        invalid = [Config([]), Config(good.devices * 2), Config(good.devices, concurrency=0),
                   Config(good.devices, timeout=float('nan'))]
        for change in ({'kind': 'ipmi'}, {'period': 0}, {'endpoint': 'udp://127.0.0.1:1'},
                       {'variables': {'Available': Variable('sensors.x')}},
                       {'variables': {'Temperature': Variable('unknown.x')}}):
            config = deepcopy(good)
            for key, value in change.items():
                setattr(config.devices[0], key, value)
            invalid.append(config)
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate(config)

    def test_common_value_conversion_rejects_bad_data(self):
        on = Variable('oid', 'Boolean', values={7: True, 8: False})
        self.assertTrue(on.convert(7))
        self.assertFalse(on.convert(8))
        for variable, value in ((on, 9), (Variable('x', 'Boolean'), 7),
                                (Variable('x', 'UInt32'), -1),
                                (Variable('x', 'Double'), float('nan')),
                                (Variable('x', 'Int32'), 2**31)):
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                variable.convert(value)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tasks = []
        self.bridge = None
        self.client = None
        self.wib_port, self.daphne_port = free_port(), free_port()
        self.pdu = PduAgent('127.0.0.1', free_port(True), outlets=2)
        await self.pdu.start()
        self.start_board('wib', self.wib_port)
        self.start_board('daphne', self.daphne_port)
        self.config = Config([
            Device('wib-1', 'wib', f'tcp://127.0.0.1:{self.wib_port}',
                   {'Temperature': Variable('sensors.ad7414_49_temp', unit='degC'),
                    'Femb0On': Variable('femb.femb_power.0', 'Boolean')}, period=0.05),
            Device('daphne-1', 'daphne', f'tcp://127.0.0.1:{self.daphne_port}',
                   {'Register': Variable('test_register.value', 'UInt32')}, period=0.05),
            Device('pdu-1', 'pdu', f'udp://127.0.0.1:{self.pdu.port}',
                   {'OutletOn': Variable('1.3.6.1.4.1.13742.6.4.1.2.1.3.1.1',
                                         'Boolean', values={7: True, 8: False})}, period=0.05),
        ], endpoint=f'opc.tcp://127.0.0.1:{free_port()}/test/', timeout=0.15, concurrency=3)

    def start_board(self, kind, port):
        task = asyncio.create_task(run_emulator(SimpleNamespace(kind=kind, host='127.0.0.1', port=port)))
        self.tasks.append(task)
        return task

    async def start_bridge(self):
        self.bridge = Bridge(self.config)
        await self.bridge.start()
        self.client = Client(self.config.endpoint)
        await self.client.connect()
        self.index = await self.client.get_namespace_index(NAMESPACE)
        await eventually(self.all_available)

    def node(self, device, name):
        return self.client.get_node(ua.NodeId(f'Devices.{device}.{name}', self.index))

    async def all_available(self):
        return all(await self.client.read_values([self.node(d.id, 'Available') for d in self.config.devices]))

    async def asyncTearDown(self):
        if self.client:
            await self.client.disconnect()
        if self.bridge:
            await self.bridge.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.pdu.close()

    async def test_mixed_native_reads_have_types_units_and_fresh_timestamps(self):
        await self.start_bridge()
        self.assertEqual(await self.node('wib-1', 'Temperature').read_value(), 28.0)
        self.assertEqual(await self.node('daphne-1', 'Register').read_value(), 0xDEADBEEF)
        self.assertFalse(await self.node('pdu-1', 'OutletOn').read_value())
        unit = self.client.get_node(ua.NodeId('Devices.wib-1.Temperature.Unit', self.index))
        self.assertEqual(await unit.read_value(), 'degC')
        before = await self.node('wib-1', 'Temperature').read_data_value()

        async def newer():
            after = await self.node('wib-1', 'Temperature').read_data_value()
            return after.SourceTimestamp > before.SourceTimestamp
        await eventually(newer)
        with self.assertRaises(ua.UaStatusCodeError):
            await self.node('wib-1', 'Temperature').write_value(123.0)
        for task in self.bridge.tasks:
            self.assertFalse(task.done())

    async def test_changed_device_state_reaches_opcua(self):
        await self.start_bridge()
        self.pdu.model.write_variables((SWITCH + (2, 1, 1), v2c.Integer32(1)))

        async def on():
            return await self.node('pdu-1', 'OutletOn').read_value()
        await eventually(on)

    async def test_device_loss_preserves_sample_time_and_recovers(self):
        await self.start_bridge()
        self.tasks[0].cancel()
        await asyncio.gather(self.tasks[0], return_exceptions=True)

        async def offline():
            return not await self.node('wib-1', 'Available').read_value()
        await eventually(offline)
        bad = await self.node('wib-1', 'Temperature').read_data_value(raise_on_bad_status=False)
        self.assertEqual(bad.StatusCode.value, ua.StatusCodes.BadNoCommunication)
        self.assertEqual(bad.SourceTimestamp, await self.node('wib-1', 'LastSuccess').read_value())
        old_sequence = await self.node('daphne-1', 'Sequence').read_value()

        async def healthy_moves():
            return await self.node('daphne-1', 'Sequence').read_value() > old_sequence
        await eventually(healthy_moves)
        self.start_board('wib', self.wib_port)
        await eventually(self.all_available)
        good = await self.node('wib-1', 'Temperature').read_data_value()
        self.assertTrue(good.StatusCode.is_good())
        self.assertGreater(good.SourceTimestamp, bad.SourceTimestamp)

    async def test_invalid_value_mapping_marks_data_bad(self):
        self.config.devices[2].variables['OutletOn'].values = {7: True}
        self.bridge = Bridge(self.config)
        await self.bridge.start()
        self.client = Client(self.config.endpoint)
        await self.client.connect()
        self.index = await self.client.get_namespace_index(NAMESPACE)

        async def decoded_bad():
            value = await self.node('pdu-1', 'OutletOn').read_data_value(raise_on_bad_status=False)
            return value.StatusCode.value == ua.StatusCodes.BadDecodingError
        await eventually(decoded_bad)
        self.assertFalse(await self.node('pdu-1', 'Available').read_value())

    async def test_metrics_and_probe_report_native_timeout_and_bad_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'metrics.json'
            self.bridge = Bridge(self.config, metrics_path=path, metrics_interval=0.05)
            await self.bridge.start()
            self.client = Client(self.config.endpoint)
            await self.client.connect()
            self.index = await self.client.get_namespace_index(NAMESPACE)
            await eventually(self.all_available)
            self.tasks[0].cancel()
            await asyncio.gather(self.tasks[0], return_exceptions=True)

            async def timeout_recorded():
                return self.bridge.metrics.snapshot()['devices']['wib-1']['timeouts'] > 0
            await eventually(timeout_recorded)
            report = await measure(self.config, duration=0.15, workers=2, pids=[os.getpid()])
            self.assertEqual(report['status'], 'completed')
            self.assertGreater(report['counts']['successful_requests'], 0)
            self.assertGreater(report['counts']['bad_values'], 0)
            self.assertEqual(report['counts']['timeouts'], 0)  # OPC UA answered; native WIB timed out.
            self.assertGreater(report['good_value_age_ms']['count'], 0)
            self.assertEqual(report['resources'][str(os.getpid())]['history'][-1]['status'], 'running')
            await self.client.disconnect()
            self.client = None
            await self.bridge.close()
            snapshot = json.loads(path.read_text())
            self.assertGreater(snapshot['by_kind']['wib']['timeouts'], 0)
            self.assertGreater(snapshot['by_kind']['daphne']['successes'], 0)
            self.assertEqual(snapshot['by_kind']['daphne']['failures'], 0)

    async def test_probe_records_connection_failure(self):
        self.config.endpoint = f'opc.tcp://127.0.0.1:{free_port()}/unavailable/'
        report = await measure(self.config, duration=0.1, timeout=0.1)
        self.assertEqual(report['status'], 'connection_failed')
        self.assertIsNotNone(report['connect_error'])
        self.assertEqual(report['counts']['requests'], 0)

    async def test_probe_counts_read_timeouts_separately_from_connect(self):
        await self.start_bridge()

        async def slow_read(client, nodes):
            await asyncio.sleep(1)

        with patch.object(Client, 'read_attributes', slow_read):
            report = await measure(self.config, duration=0.1, workers=2, timeout=0.05)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['connect_timeouts'], 0)
        self.assertGreater(report['counts']['timeouts'], 0)
        self.assertEqual(report['counts']['timeouts'], report['counts']['failed_requests'])
        self.assertEqual(report['counts']['requests'], report['counts']['failed_requests'])
