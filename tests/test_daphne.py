import unittest

from dune_dscs.emulator.daphne import Daphne
from dune_dscs.emulator.protocols._generated import daphneV3_high_level_confs_pb2 as pb


class DaphneTests(unittest.TestCase):
    def test_reply_matches_request(self):
        request = pb.ControlEnvelopeV2(version=2, dir=pb.DIR_REQUEST,
            type=pb.MT2_READ_TEST_REG_REQ, payload=pb.TestRegRequest().SerializeToString(),
            msg_id=42, task_id=7, route='mezz/0')
        response = pb.ControlEnvelopeV2.FromString(Daphne().reply(request.SerializeToString()))
        self.assertEqual((response.version, response.dir, response.type),
                         (2, pb.DIR_RESPONSE, pb.MT2_READ_TEST_REG_RESP))
        self.assertEqual((response.correl_id, response.task_id, response.route), (42, 7, 'mezz/0'))
        self.assertEqual(pb.TestRegResponse.FromString(response.payload).value, 0xDEADBEEF)

    def test_configuration_readback_and_rejected_write(self):
        model = Daphne()
        request = pb.ConfigureRequest(self_trigger_threshold=23)
        request.channels.add(id=0)
        reply = model.dispatch(pb.MT2_CONFIGURE_FE_REQ, request.SerializeToString())
        self.assertTrue(reply.success)
        request.self_trigger_threshold = 99
        request.channels.add(id=40)
        self.assertFalse(model.dispatch(pb.MT2_CONFIGURE_FE_REQ, request.SerializeToString()).success)
        counters = model.dispatch(pb.MT2_READ_TRIGGER_COUNTERS_REQ,
                                 pb.ReadTriggerCountersRequest(channels=[0, 1]).SerializeToString())
        # An invalid configuration must leave the previous thresholds intact.
        self.assertEqual([item.threshold for item in counters.snapshots], [23, 0])
        self.assertEqual(Daphne().thresholds[0], 0)

    def test_bad_envelopes_are_ignored(self):
        model = Daphne()
        for payload in (b'\xff', pb.ControlEnvelopeV2(version=1, dir=pb.DIR_REQUEST).SerializeToString(),
                        pb.ControlEnvelopeV2(version=2, dir=pb.DIR_RESPONSE).SerializeToString()):
            with self.subTest(payload=payload):
                self.assertIsNone(model.reply(payload))
