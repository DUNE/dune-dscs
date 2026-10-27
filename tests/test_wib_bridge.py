"""Exercise the existing bridge against a WIB handler over local ZeroMQ."""
import importlib.util
from pathlib import Path
from queue import Queue
from threading import Event, Thread

import pytest
import wib_pb2 as pb
import zmq

from wib.emulator.wib_emulator_v3p1 import WIBEmulator

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.chdir(ROOT / "bridge")
    spec = importlib.util.spec_from_file_location("tested_bridge", ROOT / "bridge/ignition_pybidge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.context.destroy(linger=0)


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
