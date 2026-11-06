"""Exercise the standalone protocol handlers without detector hardware."""

import asyncio

from dune_dscs.emulator.daphne import Daphne
from dune_dscs.emulator.protocols._generated import (
    daphneV3_high_level_confs_pb2 as daphne_pb,
)
from dune_dscs.emulator.protocols._generated import wib_pb2 as wib_pb
from dune_dscs.emulator.wib import Wib


def wib_request(device, request, reply_type):
    command = wib_pb.Command()
    command.cmd.Pack(request)
    reply = reply_type()
    reply.ParseFromString(asyncio.run(device.reply(command.SerializeToString())))
    return reply


def test_wib_configuration_and_registers_stay_with_the_device():
    first, second = Wib(), Wib()
    config = wib_pb.ConfigureWIB()
    config.fembs.add(enabled=True)
    assert wib_request(first, config, wib_pb.Status).success
    assert first.femb_power == [True, False, False, False]
    assert second.femb_power == [False] * 4
    wib_request(first, wib_pb.Poke(addr=4, value=0xFEDCBA98), wib_pb.RegValue)
    value = wib_request(first, wib_pb.Peek(addr=4), wib_pb.RegValue)
    assert (value.addr, value.value) == (4, 0xFEDCBA98)
    assert wib_request(second, wib_pb.Peek(addr=4), wib_pb.RegValue).value == 0


def test_wib_bad_request_does_not_break_the_next_reply():
    device = Wib()
    assert asyncio.run(device.reply(b"\xff")) == b""
    assert asyncio.run(device.reply(b"")) == b""
    reply = wib_request(device, wib_pb.GetSWVersion(), wib_pb.GetSWVersion.Version)
    assert reply.version == "detector-control-emulator"


def test_daphne_reply_keeps_envelope_correlation():
    device = Daphne()
    request = daphne_pb.ControlEnvelopeV2(
        version=2, dir=daphne_pb.DIR_REQUEST, type=daphne_pb.MT2_READ_TEST_REG_REQ,
        task_id=7, msg_id=42,
    )
    envelope = daphne_pb.ControlEnvelopeV2.FromString(device.reply(request.SerializeToString()))
    assert envelope.dir == daphne_pb.DIR_RESPONSE
    assert envelope.correl_id == 42
    assert envelope.task_id == 7
    reply = daphne_pb.TestRegResponse.FromString(envelope.payload)
    assert reply.value == 0xDEADBEEF
    assert device.reply(b"\xff") is None


def test_daphne_rejects_invalid_channels_without_changing_configuration():
    device = Daphne()
    valid = daphne_pb.ConfigureRequest()
    valid.channels.add(id=0)
    assert device.dispatch(daphne_pb.MT2_CONFIGURE_FE_REQ, valid.SerializeToString()).success
    previous = device.config.SerializeToString()
    invalid = daphne_pb.ConfigureRequest()
    invalid.channels.add(id=40)
    reply = device.dispatch(daphne_pb.MT2_CONFIGURE_FE_REQ, invalid.SerializeToString())
    assert reply.success is False
    assert device.config.SerializeToString() == previous
