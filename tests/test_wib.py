import unittest

from dune_dscs.emulator.protocols._generated import wib_pb2 as pb
from dune_dscs.emulator.wib import Wib


class WibTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, model, request, response_type):
        command = pb.Command()
        command.cmd.Pack(request)
        return response_type.FromString(await model.reply(command.SerializeToString()))

    async def test_power_readback_and_independent_devices(self):
        first, second = Wib(), Wib()
        response = await self.request(first, pb.PowerWIB(femb0=True), pb.Status)
        self.assertTrue(response.success)
        for model, expected in ((first, [True, False, False, False]), (second, [False] * 4)):
            status = await self.request(model, pb.GetFEMBStatus(), pb.GetFEMBStatus.FEMBStatus)
            self.assertEqual(list(status.femb_power), expected)

    async def test_configuration_readback(self):
        model = Wib()
        request = pb.ConfigureWIB()
        request.fembs.add(enabled=True)
        request.fembs.add(enabled=False)
        request.fembs.add(enabled=True)
        response = await self.request(model, request, pb.Status)
        self.assertTrue(response.success)
        status = await self.request(model, pb.GetFEMBStatus(), pb.GetFEMBStatus.FEMBStatus)
        self.assertEqual(list(status.femb_power), [True, False, True, False])

    async def test_bad_request_then_raw_sensor_reply(self):
        model = Wib()
        self.assertEqual(await model.reply(b'\xff'), b'')
        # The reply is Sensors itself, without an Any or Command wrapper.
        sensors = await self.request(model, pb.GetSensors(), pb.GetSensors.Sensors)
        self.assertEqual(sensors.ad7414_49_temp, 28.0)
        self.assertEqual(len(sensors.ltc2990_4e_voltages), 4)
