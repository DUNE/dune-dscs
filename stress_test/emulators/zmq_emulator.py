import os
import random

import zmq
from google.protobuf.any_pb2 import Any

import zmq_em_pb2


class WIBEmulator:
    """Interpret requests and construct simulated sensor responses."""

    def __init__(self):
        self.ADDRESSGLOVAL = 0x0000

    def handle_request(self, raw_msg: bytes):
        """Decode a request and return the serialized sensor response."""
        msg_any = Any()

        try:
            msg_any.ParseFromString(raw_msg)
        except Exception as error:
            print(f"[!] Error parsing protobuf Any: {error}")
            return None

        if msg_any.type_url.endswith("zmq_em.GetSensors"):
            reply = zmq_em_pb2.GetSensors()

            reply.Temp1 = 24 + random.gauss(0, 0.5)
            reply.vol1.append(12 + random.gauss(0, 0.1))
            reply.vol1.append(22 + random.gauss(0, 0.1))

            print("Temo1 = ", reply.Temp1)
            print("vol1[0] = ", reply.vol1[0])
            print("vol1[1] = ", reply.vol1[1])
            print("[OK] Sent sensor readings")

            return reply.SerializeToString()

        print("Unknown type:", msg_any.type_url)
        return b""


def main():
    """Start the ZeroMQ reply socket and process requests."""
    context = zmq.Context()
    socket = context.socket(zmq.REP)

    port = int(os.environ.get("EMULATOR_PORT", "5555"))
    socket.bind(f"tcp://*:{port}")
    print(f"ZMQ Emulator running on port {port}", flush=True)

    emulator = WIBEmulator()

    while True:
        try:
            raw = socket.recv()
            reply = emulator.handle_request(raw)

            if reply:
                socket.send(reply)
            else:
                print("Wrong message, the reply is empty")
                socket.send(b"")

        except Exception as error:
            print(f"[!] Runtime error: {error}")
            socket.send(b"")


if __name__ == "__main__":
    main()