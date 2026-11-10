#!/usr/bin/env python3
"""Run the ZeroMQ-to-OPC-UA bridge and record per-cycle diagnostics."""

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil
import zmq
from google.protobuf.any_pb2 import Any
from opcua import Server, ua

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "opc.tcp://0.0.0.0:4840/freeopcua/server/"
CONTROL_FILE = ROOT / "ignition_test_control.json"
REQUEST_TIMEOUT_MS = 10_000
CYCLE_DELAY_S = 1

# Ordering must match the device ordering in the Ignition diagnostic script.
EMULATOR_HOSTS = [
    (3, "134.93.131.35"),
    (6, "134.93.128.228"),
    (7, "134.93.128.229"),
    (2, "134.93.130.214"),
    (9, "134.93.128.243"),
    (10, "134.93.129.24"),
    (11, "134.93.129.16"),
    (12, "134.93.131.161"),
    (14, "134.93.129.26"),
]

CSV_COLUMNS = [
    "time_utc", "cycle", "devices", "variables", "cycle_s",
    "cpu_percent", "ram_mb", "attempts", "successes", "timeouts",
    "send_errors", "other_errors", "failure_percent", "acquisitions_per_s",
    "mean_request_ms", "zmq_tx_payload_kB_s", "zmq_rx_payload_kB_s",
    "node_writes", "node_writes_per_s", "parse_total_ms", "update_total_ms",
    "request_median_ms", "request_p95_ms", "request_p99_ms",
]


class MissingAttributeFilter(logging.Filter):
    """Suppress the existing missing-attribute-23 warning."""

    def filter(self, record):
        message = record.getMessage()
        return not (
            "Tried to read attribute '23'" in message
            and "but the attribute is missing" in message
        )


def reset_metrics():
    """Return empty counters and timings for one polling cycle."""
    return {
        "attempts": 0,
        "successes": 0,
        "timeouts": 0,
        "send_errors": 0,
        "other_errors": 0,
        "latencies_ms": [],
        "tx_bytes": 0,
        "rx_bytes": 0,
        "node_writes": 0,
        "parse_ms": 0.0,
        "update_ms": 0.0,
    }


def make_devices(number):
    """Distribute devices round-robin across the configured hosts."""
    devices = []

    for index in range(number):
        weber, host = EMULATOR_HOSTS[index % len(EMULATOR_HOSTS)]
        device = index // len(EMULATOR_HOSTS) + 1
        devices.append({
            "tpc": weber,
            "dev": device,
            "host": host,
            "port": 5554 + device,
        })

    return devices


def initialize_nodes(parent, namespace, nodes, mapping, tpc, device):
    """Create sensor objects and variables with the existing node IDs."""
    for name, count in mapping.items():
        sensor_object = parent.add_object(namespace, name)
        nodes[name] = []
        initial_value = 0 if name == "addr" else 0.0

        for index in range(count):
            node_id = ua.NodeId(
                f"TPC{tpc}/WIB{device}/{name}/{index}", namespace
            )
            variable = sensor_object.add_variable(
                node_id, f"{name}_{index}", initial_value
            )
            variable.set_writable()
            nodes[name].append(variable)


def update_node(response, nodes, metrics):
    """Copy response fields into one device's nodes and count writes."""
    for name, variables in nodes.items():
        if not hasattr(response, name):
            continue

        value = getattr(response, name)

        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            for variable, item in zip(variables, value):
                variable.set_value(item)
                metrics["node_writes"] += 1
        elif variables:
            variables[0].set_value(value)
            metrics["node_writes"] += 1


def zmqd_request(
    context, device, metrics, request, response_class,
    use_any_response=True,
):
    """Send an Any-wrapped request and measure the reply and parsing."""
    metrics["attempts"] += 1
    request_socket = context.socket(zmq.REQ)
    host = device["host"]
    port = device["port"]
    machine = f"Weber{device['tpc']:02d}"
    stage = "setup"

    try:
        request_socket.connect(f"tcp://{host}:{port}")
        request_socket.setsockopt(zmq.RCVTIMEO, REQUEST_TIMEOUT_MS)

        envelope = Any()
        envelope.Pack(request)
        request_bytes = envelope.SerializeToString()

        stage = "send"
        started = time.perf_counter()
        request_socket.send(request_bytes, flags=zmq.DONTWAIT)
        metrics["tx_bytes"] += len(request_bytes)

        stage = "receive"
        response_bytes = request_socket.recv()
        request_ms = (time.perf_counter() - started) * 1000
        metrics["rx_bytes"] += len(response_bytes)

        stage = "parse"
        parse_started = time.perf_counter()

        try:
            response = response_class()

            if use_any_response:
                envelope = Any()
                envelope.ParseFromString(response_bytes)
                if not envelope.Unpack(response):
                    raise ValueError("Unexpected protobuf response type")
            else:
                response.ParseFromString(response_bytes)
        finally:
            metrics["parse_ms"] += (
                time.perf_counter() - parse_started
            ) * 1000

        metrics["successes"] += 1
        metrics["latencies_ms"].append(request_ms)
        return response

    except zmq.error.Again:
        if stage == "receive":
            metrics["timeouts"] += 1
        elif stage == "send":
            metrics["send_errors"] += 1
        else:
            metrics["other_errors"] += 1

        print(f"[!] {stage} failed: Sensors on {machine}, port {port}")
        return None

    except Exception as error:
        if stage == "send":
            metrics["send_errors"] += 1
        else:
            metrics["other_errors"] += 1

        print(f"[!] {stage} error on {machine}:{port}: {error}")
        return None

    finally:
        request_socket.close(linger=0)


def percentile(sorted_values, percent):
    """Calculate a percentile using linear interpolation."""
    if not sorted_values:
        return None

    position = (len(sorted_values) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower

    return (
        sorted_values[lower]
        + fraction * (sorted_values[upper] - sorted_values[lower])
    )


def update_ignition_control(number, run_id, active):
    """Atomically update the control file read by Ignition."""
    temporary = CONTROL_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "N": number,
        "run_id": run_id,
        "active": active,
    }))
    os.replace(temporary, CONTROL_FILE)


def parse_arguments():
    """Read and validate the existing command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--devices", type=int, required=True,
        help="Number of emulators to poll (1–1000).",
    )
    parser.add_argument(
        "--cycles", type=int, default=10,
        help="Number of measured cycles after warm-up (default: 10).",
    )
    parser.add_argument(
        "--warmup", type=float, default=30,
        help="Warm-up duration in seconds (default: 30).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "results",
        help="CSV directory (default: stress_test/results).",
    )
    args = parser.parse_args()

    if args.cycles < 1:
        parser.error("--cycles must be at least 1")
    if not 1 <= args.devices <= 1000:
        parser.error("--devices must be between 1 and 1000")
    if not math.isfinite(args.warmup) or args.warmup < 0:
        parser.error("--warmup must be finite and nonnegative")

    return args


def main():
    """Set up the bridge, poll devices and save measured cycles."""
    args = parse_arguments()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Load local modules after locating the shared Protobuf module.
    sys.path.insert(0, str(ROOT))
    import zmq_em_pb2
    from zmq_sensor_config import ZMQSensorConfig

    logging.getLogger("opcua.server.address_space").addFilter(
        MissingAttributeFilter()
    )

    sensor_config = ZMQSensorConfig()
    mappings = [
        sensor_config.get_voltages(),
        sensor_config.get_temperatures(),
    ]
    devices = make_devices(args.devices)

    server = Server()
    server.set_endpoint(ENDPOINT)
    server.set_server_name("ZMQ-Ignition Bridge Server")
    namespace = server.register_namespace("")
    objects = server.get_objects_node()
    nodes = {}

    for device in devices:
        tpc = device["tpc"]
        number = device["dev"]
        key = (tpc, number)
        nodes[key] = {}
        parent = objects.add_object(namespace, f"TPC{tpc}_ZMQD{number}")

        for mapping in mappings:
            initialize_nodes(
                parent, namespace, nodes[key], mapping, tpc, number
            )

    variable_count = sum(
        len(variables)
        for device_nodes in nodes.values()
        for variables in device_nodes.values()
    )
    filename = args.output_dir / f"bridge_N{len(devices)}.csv"
    run_id = uuid.uuid4().hex

    # Exclusive creation preserves the existing no-overwrite behaviour.
    with open(filename, "x", newline="") as csv_file:
        with zmq.Context() as context:
            server_started = False

            try:
                server.start()
                server_started = True
                print(f"Server started at {server.endpoint}")
                update_ignition_control(args.devices, run_id, True)

                writer = csv.writer(csv_file)
                writer.writerow(CSV_COLUMNS)
                print("Saving diagnostics to:", filename)

                process = psutil.Process()
                process.cpu_percent(None)
                count = 0
                warmup_started = time.perf_counter()
                warming_up = args.warmup > 0

                while count < args.cycles:
                    metrics = reset_metrics()
                    cycle_started = time.perf_counter()
                    time.sleep(CYCLE_DELAY_S)

                    if warming_up:
                        print(f"\n=== Warm-up; Ndevices: {len(devices)} ===")
                    else:
                        count += 1
                        print(
                            f"\n=== cycle {count}/{args.cycles}; "
                            f"Ndevices: {len(devices)} ==="
                        )

                    for device in devices:
                        response = zmqd_request(
                            context, device, metrics,
                            zmq_em_pb2.GetSensors(), zmq_em_pb2.GetSensors,
                            use_any_response=False,
                        )

                        if response is not None:
                            update_started = time.perf_counter()
                            try:
                                update_node(
                                    response,
                                    nodes[(device["tpc"], device["dev"])],
                                    metrics,
                                )
                            finally:
                                metrics["update_ms"] += (
                                    time.perf_counter() - update_started
                                ) * 1000

                    if warming_up:
                        elapsed = time.perf_counter() - warmup_started
                        process.cpu_percent(None)

                        if elapsed >= args.warmup:
                            warming_up = False
                            print(
                                f"Warm-up finished after {elapsed:.1f} s. "
                                "Starting measured cycles."
                            )

                        continue

                    cycle_s = time.perf_counter() - cycle_started
                    cpu = process.cpu_percent(None)
                    ram_mb = process.memory_info().rss / 1_000_000
                    failures = (
                        metrics["timeouts"]
                        + metrics["send_errors"]
                        + metrics["other_errors"]
                    )
                    failure_percent = (
                        100 * failures / metrics["attempts"]
                        if metrics["attempts"] else None
                    )
                    latencies = metrics["latencies_ms"]
                    mean_request_ms = (
                        sum(latencies) / len(latencies)
                        if latencies else None
                    )

                    sorted_latencies = sorted(latencies)

                    writer.writerow([
                        datetime.now(timezone.utc).isoformat(),
                        count, len(devices), variable_count,
                        round(cycle_s, 3), cpu, round(ram_mb, 2),
                        metrics["attempts"], metrics["successes"],
                        metrics["timeouts"], metrics["send_errors"],
                        metrics["other_errors"], failure_percent,
                        metrics["successes"] / cycle_s,
                        mean_request_ms,
                        metrics["tx_bytes"] / 1000 / cycle_s,
                        metrics["rx_bytes"] / 1000 / cycle_s,
                        metrics["node_writes"],
                        metrics["node_writes"] / cycle_s,
                        metrics["parse_ms"], metrics["update_ms"],
                        percentile(sorted_latencies, 50),
                        percentile(sorted_latencies, 95),
                        percentile(sorted_latencies, 99),
                    ])
                    csv_file.flush()

                    print(
                        f"Cycle {count}/{args.cycles}: "
                        f"{cycle_s:.2f} s | CPU {cpu:.1f}% | "
                        f"RAM {ram_mb:.1f} MB"
                    )

            except KeyboardInterrupt:
                pass
            finally:
                if server_started:
                    try:
                        update_ignition_control(args.devices, run_id, False)
                    finally:
                        server.stop()
                        print("Server stopped")


if __name__ == "__main__":
    main()
