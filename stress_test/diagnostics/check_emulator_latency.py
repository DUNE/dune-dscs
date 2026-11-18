#!/usr/bin/env python3
"""Compare fresh and reused ZeroMQ connections on selected emulator ports."""

import argparse
import csv
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import zmq
from google.protobuf.any_pb2 import Any
from google.protobuf.message import DecodeError
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ("Weber06", "134.93.128.228", 5564),
    ("Weber06", "134.93.128.228", 5610),
    ("Weber12", "134.93.131.161", 5564),
    ("Weber12", "134.93.131.161", 5610),
    ("Weber03-control", "134.93.131.35", 5564),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1000,
                        help="Requests per endpoint per connection mode")
    parser.add_argument("--timeout", type=float, default=3,
                        help="Receive timeout in seconds (default: 3)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "emulator_latency.csv")
    args = parser.parse_args()
    if args.samples < 1 or not math.isfinite(args.timeout) or args.timeout < 1:
        parser.error("Use positive samples and a timeout of at least 1 s")

    sys.path.insert(0, str(ROOT))
    import zmq_em_pb2

    envelope = Any()
    envelope.Pack(zmq_em_pb2.GetSensors())
    request = envelope.SerializeToString()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    total = len(TARGETS) * 2 * args.samples
    print("Run on the bridge host, with the bridge stopped.")
    print("A valid reply after 1 s is labelled late; receive limit is "
          f"{args.timeout:g} s. Input files are not modified.")

    with args.output.open("x", newline="") as file, zmq.Context() as context:
        writer = csv.writer(file)
        writer.writerow(["time_utc", "host", "address", "port", "device",
                         "mode", "request", "request_ms", "result"])
        with tqdm(total=total, desc="Checking latency", unit="request") as bar:
            for host, address, port in TARGETS:
                for mode in ("fresh", "reused"):
                    socket = None
                    try:
                        for index in range(args.samples):
                            started = time.perf_counter()
                            result = "ok"
                            try:
                                if socket is None:
                                    socket = context.socket(zmq.REQ)
                                    socket.setsockopt(zmq.LINGER, 0)
                                    socket.setsockopt(
                                        zmq.RCVTIMEO, int(args.timeout * 1000),
                                    )
                                    socket.connect(f"tcp://{address}:{port}")
                                # Match the bridge's send-to-receive window.
                                started = time.perf_counter()
                                socket.send(request, flags=zmq.DONTWAIT)
                                raw = socket.recv()
                                received = time.perf_counter()
                                response = zmq_em_pb2.GetSensors()
                                response.ParseFromString(raw)
                                if not raw or len(response.vol1) != 2:
                                    result = "invalid_reply"
                                elif received - started > 1:
                                    result = "late_reply"
                            except zmq.Again:
                                received = time.perf_counter()
                                result = "send_or_receive_timeout"
                            except (zmq.ZMQError, DecodeError) as error:
                                received = time.perf_counter()
                                result = type(error).__name__
                            writer.writerow([
                                datetime.now(timezone.utc).isoformat(),
                                host, address, port, port - 5554, mode,
                                index + 1,
                                round((received - started) * 1000, 3),
                                result,
                            ])
                            counts[(host, port, mode, result)] += 1
                            if mode == "fresh" or result not in (
                                "ok", "late_reply",
                            ):
                                if socket is not None:
                                    socket.close()
                                socket = None
                            if index % 100 == 0:
                                file.flush()
                            bar.update(1)
                    finally:
                        if socket is not None:
                            socket.close()
    print("\nHost                 Port  Mode      Result                 Count")
    for (host, port, mode, result), count in sorted(counts.items()):
        print(f"{host:<20} {port:<5} {mode:<9} {result:<24} {count}")
    print(f"\nSaved {args.output.resolve()}")
    print("Results locate delays; they do not prove a network or host cause.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped; partial CSV preserved.")
        raise SystemExit(130)
