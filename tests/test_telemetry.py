import socket
import unittest

from pysnmp.hlapi.v3arch.asyncio import SnmpEngine
from pysnmp.proto.api import v2c

from dune_dscs.bridge import Variable
from dune_dscs.bridge_clients import PduClient
from dune_dscs.emulator.daphne import Daphne
from dune_dscs.emulator.pdu import Pdu, PduAgent
from dune_dscs.emulator.protocols._generated import (
    daphneV3_high_level_confs_pb2 as daphne,
)
from dune_dscs.emulator.protocols._generated import wib_pb2 as wib
from dune_dscs.emulator.telemetry import Telemetry
from dune_dscs.emulator.wib import Wib


class TelemetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.telemetry = Telemetry(seed=0, period=60, clock=lambda: self.now)

    def test_repeatable_time_based_drift_and_bounds(self):
        same = Telemetry(seed=0, period=60, clock=lambda: self.now)
        different = Telemetry(seed=1, period=60, clock=lambda: self.now)
        self.assertEqual(self.telemetry.analog(28, .5), same.analog(28, .5))
        self.assertNotEqual(self.telemetry.analog(28, .5), different.analog(28, .5))
        for seconds in range(121):
            self.now = 100 + seconds
            value = self.telemetry.analog(28, .5)
            self.assertGreaterEqual(value, 27.5)
            self.assertLessEqual(value, 28.5)
            self.assertEqual(value, self.telemetry.analog(28, .5))
        for period in (0, -1, float('nan'), float('inf')):
            with self.subTest(period=period), self.assertRaises(ValueError):
                Telemetry(period=period)

    async def test_wib_temperature_changes_without_changing_power(self):
        model = Wib(telemetry=self.telemetry)
        await model.configure([True, False, True, False])
        command = wib.Command()
        command.cmd.Pack(wib.GetSensors())
        first = wib.GetSensors.Sensors.FromString(await model.reply(command.SerializeToString()))
        self.now += 15
        second = wib.GetSensors.Sensors.FromString(await model.reply(command.SerializeToString()))
        self.assertEqual(first.ad7414_49_temp, 28)
        self.assertEqual(second.ad7414_49_temp, 28.5)
        self.assertEqual(model.femb_power, [True, False, True, False])

    def test_daphne_sensors_counters_and_configured_values(self):
        model = Daphne(telemetry=self.telemetry)
        request = daphne.ConfigureRequest(self_trigger_threshold=23)
        request.channels.add(id=0)
        self.assertTrue(model.dispatch(daphne.MT2_CONFIGURE_FE_REQ, request.SerializeToString()).success)
        info = model.dispatch(daphne.MT2_READ_GENERAL_INFO_REQ, b'')
        self.now += 15
        changed = model.dispatch(daphne.MT2_READ_GENERAL_INFO_REQ, b'')
        for name in info.DESCRIPTOR.fields_by_name:
            self.assertNotEqual(getattr(info, name), getattr(changed, name))
        counters = model.dispatch(daphne.MT2_READ_TRIGGER_COUNTERS_REQ, b'')
        self.assertEqual(len(counters.snapshots), 40)
        self.assertEqual(counters.snapshots[0].threshold, 23)
        self.assertEqual(counters.snapshots[0].record_count, 1500)
        self.assertEqual(counters.snapshots[0].busy_count, 15)
        self.assertEqual(counters.snapshots[0].full_count, 1)
        self.assertEqual(model.dispatch(daphne.MT2_READ_TRIGGER_COUNTERS_REQ, b''), counters)
        self.assertEqual(model.dispatch(daphne.MT2_READ_TEST_REG_REQ, b'').value, 0xDEADBEEF)

    def test_pdu_reading_scaling_and_power_off(self):
        model = Pdu(2, telemetry=self.telemetry)
        current = (1, 3, 6, 1, 4, 1, 13742, 6, 5, 4, 3, 1, 4, 1, 1, 1)
        voltage = current[:-1] + (4,)

        def read(oid):
            return int(model.read_variables((oid, None))[0][1])

        self.assertEqual((read(current), read(voltage)), (0, 0))
        model.write_variables(((1, 3, 6, 1, 4, 1, 13742, 6, 4, 1, 2, 1, 2, 1, 1), v2c.Integer32(1)))
        first = (read(current), read(voltage))
        self.assertTrue(300 <= first[0] <= 400)
        self.assertTrue(119500 <= first[1] <= 120500)
        digits = (1, 3, 6, 1, 4, 1, 13742, 6, 3, 5, 4, 1, 7, 1, 1, 1)
        self.assertEqual(read(digits), 3)
        self.now += 15
        self.assertNotEqual(first, (read(current), read(voltage)))
        self.assertEqual(len(model.outlets), 2)

    def test_full_pdu_catalogue_and_scaled_readings(self):
        model = Pdu(10, telemetry=self.telemetry, full=True)
        self.assertEqual(len(model.monitoring.variables), 608)
        for name, settings in model.monitoring.variables.items():
            variable = Variable(**settings)
            oid = tuple(map(int, variable.source.split('.')))
            raw = model.read_variables((oid, None))[0][1]
            raw = raw.asOctets().decode() if hasattr(raw, 'asOctets') else int(raw)
            value = variable.convert(raw)
            if name.startswith('External') and name.endswith('Available'):
                self.assertIs(value, False)
        self.assertAlmostEqual(Variable('x', scale=.001).convert(350), .35)
        self.assertEqual(model.monitoring.variables['Outlet1_rmsVoltage']['unit'], 'V')
        self.assertNotIn('External1_onOff', model.monitoring.variables)

    async def test_full_pdu_readout_over_udp(self):
        with socket.socket(type=socket.SOCK_DGRAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        agent = PduAgent('127.0.0.1', port, full=True, telemetry=self.telemetry)
        snmp = SnmpEngine()
        await agent.start()
        try:
            client = PduClient('127.0.0.1', port, 'private', snmp, 2)
            variables = {name: Variable(**settings) for name, settings in agent.model.monitoring.variables.items()}
            readings = await client.read(v.source for v in variables.values())
            self.assertEqual(len(readings), len({v.source for v in variables.values()}))
            for variable in variables.values():
                variable.convert(readings[variable.source])
            self.assertEqual(variables['OutletCount'].convert(readings[variables['OutletCount'].source]), 10)
        finally:
            snmp.close_dispatcher()
            await agent.close()
