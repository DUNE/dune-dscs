"""Exercise the existing bridge against a WIB handler over local ZeroMQ."""
import importlib.util
from pathlib import Path
from queue import Queue
import socket
from threading import Event, Thread
from unittest.mock import Mock

from opcua import Client
import pytest
import wib_pb2 as pb
import zmq

from wib.emulator.wib_emulator_v3p1 import WIBEmulator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.chdir(ROOT / "bridge")
    spec = importlib.util.spec_from_file_location("tested_bridge", ROOT / "bridge/ignition_pybridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = module.context
    yield module
    context.destroy(linger=0)


@pytest.fixture
def wib_server():
    emulator = WIBEmulator()
    stop = Event()
    ports = Queue()

    def serve():
        with zmq.Context() as context:
            with context.socket(zmq.REP) as socket:
                ports.put(socket.bind_to_random_port("tcp://127.0.0.1"))
                while not stop.is_set():
                    if socket.poll(50):
                        socket.send(emulator.handle_request(socket.recv()))

    thread = Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield emulator, ports.get(timeout=3)
    finally:
        stop.set()
        thread.join(timeout=3)
        assert not thread.is_alive()


@pytest.mark.parametrize("message, reply_type, field, expected", [
    (pb.GetSWVersion(), pb.GetSWVersion.Version, "version", "v1.0.0-emulated"),
    (pb.GetTimingStatus(), pb.GetTimingStatus.TimingStatus, "ept_status", 5),
    (pb.GetSensors(), pb.GetSensors.Sensors, "ltc2990_4c_voltages", 4),
    (pb.GetTimestamp(), pb.GetTimestamp.Timestamp, "timestamp", None),
])
def test_bridge_reads_native_wib_replies(bridge, wib_server, message, reply_type, field, expected):
    _, port = wib_server
    reply = bridge.wib_request(port, message, reply_type, field)
    assert reply is not None
    value = getattr(reply, field)
    if field == "ltc2990_4c_voltages":
        assert len(value) == expected
    elif expected is None:
        assert value > 0
    else:
        assert value == expected


@pytest.mark.parametrize("message", [
    pb.Poke(addr=4, value=42), pb.PowerWIB(femb0=True), pb.ResetTiming(), pb.ConfigureWIB(),
])
def test_monitor_rejects_control_commands_before_opening_a_socket(bridge, monkeypatch, message):
    context = Mock()
    monkeypatch.setattr(bridge, "context", context)
    with pytest.raises(ValueError):
        bridge.wib_request(5555, message, pb.Status, "control")
    context.socket.assert_not_called()


def test_monitoring_only_reads_and_publishes_read_only_values(bridge, wib_server, monkeypatch):
    emulator, port = wib_server
    received = []
    handle_request = emulator.handle_request

    def record_request(data):
        command = pb.Command()
        command.ParseFromString(data)
        received.append(command.cmd.TypeName())
        return handle_request(data)

    monkeypatch.setattr(emulator, "handle_request", record_request)
    server = bridge.Server()
    idx = server.register_namespace("urn:dune:test")
    parent = server.get_objects_node().add_object(idx, "WIB1")
    wib = bridge.WIB(tpc=0, wib=1, host="localhost", port=port)
    nodes = {}
    for mapping, label in [(wib.voltages, "sensors"), (wib.temperatures, "sensors"),
                           (wib.version, "sw_version"), (wib.timestamp, "timestamp"),
                           (wib.timingstatus, "timing")]:
        bridge.initialize_nodes(parent, idx, nodes, mapping, 0, 1, label)
    simple_nodes = bridge.initialize_simple_nodes(parent, idx, "instrument1", ["temperature"])

    registers_before = emulator.registers.copy()
    power_before = emulator.state.copy()
    bridge.poll_wib(wib, {(0, 1): nodes})

    assert received == ["wib.GetSWVersion", "wib.GetTimingStatus", "wib.GetSensors", "wib.GetTimestamp"]
    assert emulator.registers == registers_before
    assert emulator.state == power_before
    assert nodes["version"][0].get_value() == "v1.0.0-emulated"
    assert nodes["version"][0].get_data_type_as_variant_type() == bridge.ua.VariantType.String
    assert nodes["ept_status"][0].get_value() == 5
    for variables in nodes.values():
        for node in variables:
            assert bridge.ua.AccessLevel.CurrentWrite not in node.get_access_level()
    assert bridge.ua.AccessLevel.CurrentWrite not in simple_nodes["temperature"].get_access_level()

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        opcua_port = listener.getsockname()[1]
    endpoint = f"opc.tcp://127.0.0.1:{opcua_port}/test"
    server.set_endpoint(endpoint)
    server.start()
    try:
        with Client(endpoint) as client:
            version = client.get_node(nodes["version"][0].nodeid)
            assert version.get_value() == "v1.0.0-emulated"
            with pytest.raises(bridge.ua.UaStatusCodeError) as error:
                version.set_value("changed by client")
            assert error.value.code == bridge.ua.StatusCodes.BadUserAccessDenied
    finally:
        server.stop()
