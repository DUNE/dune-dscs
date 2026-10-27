import pytest
import wib_pb2 as pb

from wib.emulator.wib_emulator_v3p1 import WIBEmulator


def request(emulator, message, reply_type):
    command = pb.Command()
    command.cmd.Pack(message)
    reply = reply_type()
    reply.ParseFromString(emulator.handle_request(command.SerializeToString()))
    return reply


def test_peek_reads_the_requested_address():
    reply = request(WIBEmulator(), pb.Peek(addr=4), pb.RegValue)
    assert reply.addr == 4
    assert reply.value == 456


def test_poke_changes_only_that_emulators_requested_register():
    first, second = WIBEmulator(), WIBEmulator()
    reply = request(first, pb.Poke(addr=4, value=42), pb.RegValue)
    assert (reply.addr, reply.value) == (4, 42)
    assert request(first, pb.Peek(addr=4), pb.RegValue).value == 42
    assert request(first, pb.Peek(addr=0), pb.RegValue).value == 123
    assert request(second, pb.Peek(addr=4), pb.RegValue).value == 456


def test_power_command_returns_status_and_keeps_state_on_the_emulator():
    emulator = WIBEmulator()
    reply = request(emulator, pb.PowerWIB(femb0=True, cold=True, stage=2), pb.Status)
    assert reply.success
    assert emulator.state == {"femb": [True, False, False, False], "cold": True, "stage": 2}


@pytest.mark.parametrize("data", [b"\xff", b"", pb.Empty().SerializeToString()])
def test_bad_or_unknown_request_does_not_break_the_next_request(data):
    emulator = WIBEmulator()
    assert emulator.handle_request(data) == b""
    reply = request(emulator, pb.GetSWVersion(), pb.GetSWVersion.Version)
    assert reply.version == "v1.0.0-emulated"
