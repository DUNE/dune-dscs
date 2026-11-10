###### Diagnostic imports
import argparse
import psutil
import csv
from datetime import datetime, timezone
import json
import os
import uuid
from pathlib import Path


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
from opcua import Server, ua
import zmq
from google.protobuf.any_pb2 import Any
import zmq_em_pb2
from zmq_devices_config import ZMQDevicesConfig
from zmq_sensor_config import ZMQSensorConfig

WEBER_NAMES = {
    "134.93.130.184": "Weber01",
    "134.93.130.214": "Weber02",
    "134.93.131.35": "Weber03",
    "134.93.128.228": "Weber06",
    "134.93.128.229": "Weber07",
    "134.93.128.234": "Weber08",
    "134.93.128.243": "Weber09",
    "134.93.129.24": "Weber10",
    "134.93.129.16": "Weber11",
    "134.93.131.161": "Weber12",
    "134.93.129.22": "Weber13",
    "134.93.129.26": "Weber14",
}

#EMULATOR_HOSTS = [
#    "134.93.131.35",   # Weber03
#    "134.93.128.228",  # Weber06
#    "134.93.128.229",  # Weber07
#    "134.93.128.234",  # Weber08
#    "134.93.128.243",  # Weber09
#    "134.93.129.24",   # Weber10
#    "134.93.129.16",   # Weber11
#    "134.93.131.161",  # Weber12
#    "134.93.129.22",   # Weber13
#    "134.93.129.26",   # Weber14
#]

EMULATOR_HOSTS = [
    "134.93.131.35",   # Weber03
    "134.93.128.228",  # Weber06
    "134.93.128.229",  # Weber07
    "134.93.128.234",  # Weber08
    "134.93.128.243",  # Weber09
    "134.93.129.24",   # Weber10
    "134.93.129.16",   # Weber11
    "134.93.131.161",  # Weber12
    "134.93.130.214",  # Weber02 — replaces Weber13
    "134.93.129.26",   # Weber14
]

context = zmq.Context()
socket = context.socket(zmq.REQ) #request socket

#cfg = ZMQDevicesConfig()
#print("Loaded WIBs from config:")
#for wib in cfg.get_devices():
#    print(f"  TPC{wib['tpc']} WIB{wib['wib']} -> port {wib['port']}")


zmq_sensor_cfg = ZMQSensorConfig() ## load sensor configurations and separate variable sin labels 
SENSOR_MAP_V = zmq_sensor_cfg.get_voltages()
SENSOR_MAP_Temp = zmq_sensor_cfg.get_temperatures()
#print("Loaded WIB sensor fields from config:")

##########################
metrics = {}


def reset_metrics():
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
##########################



class ZMQ:
    def __init__(self, tpc, dev, host, port):
        self.tpc = tpc
        self.dev = dev
        self.host = host
        self.port = port
        self.voltages = {name: [0.0] * n for name, n in SENSOR_MAP_V.items()}
        self.temperatures = {name: [0.0] * n for name, n in SENSOR_MAP_Temp.items()}

def initialize_nodes(parent, idx, nodes, mapping, tpc, izmq):
    """Create one OPC UA object + variables per entry in `mapping`, under `parent`."""
    for name, values in mapping.items():
        obj = parent.add_object(idx, name)
        nodes[name] = []

        init_value = 0 if name == "addr" else 0.0

        for i in range(len(values)):
            nodeid = ua.NodeId(f"TPC{tpc}/WIB{izmq}/{name}/{i}", idx)
            var = obj.add_variable(nodeid, f"{name}_{i}", init_value)
            var.set_writable()
            nodes[name].append(var)

    return nodes


def update_node(resp_msg, nodes_by_zmq, dev):
    """Copy the fields of a protobuf response into the OPC UA nodes for one WIB."""
    zmq_nodes = nodes_by_zmq[(dev.tpc, dev.dev)]

    for name in zmq_nodes.keys():
        if not hasattr(resp_msg, name):
            continue

        value = getattr(resp_msg, name)

        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            for i, v in enumerate(value):
                if i < len(zmq_nodes[name]):
                    zmq_nodes[name][i].set_value(v)
                    metrics["node_writes"] += 1
        elif len(zmq_nodes[name]) > 0:
            zmq_nodes[name][0].set_value(value)
            metrics["node_writes"] += 1

    return nodes_by_zmq




def zmqd_request(
    host, port, req_msg, resp_msg_class, label,
    use_any_response=True
):
    metrics["attempts"] += 1
    zmq_socket = context.socket(zmq.REQ)
    machine = WEBER_NAMES.get(host, host)
    stage = "setup"

    try:
        zmq_socket.connect(f"tcp://{host}:{port}")
        #zmq_socket.setsockopt(zmq.RCVTIMEO, 2000)
        zmq_socket.setsockopt(zmq.RCVTIMEO, 10_000)

        req_any = Any()
        req_any.Pack(req_msg)
        request_bytes = req_any.SerializeToString()

        stage = "send"
        start = time.perf_counter()
        zmq_socket.send(request_bytes, flags=zmq.DONTWAIT)
        metrics["tx_bytes"] += len(request_bytes)

        stage = "receive"
        resp_bytes = zmq_socket.recv()
        request_ms = (time.perf_counter() - start) * 1000
        metrics["rx_bytes"] += len(resp_bytes)

        stage = "parse"
        parse_start = time.perf_counter()

        try:
            resp_msg = resp_msg_class()

            if use_any_response:
                resp_any = Any()
                resp_any.ParseFromString(resp_bytes)
                if not resp_any.Unpack(resp_msg):
                    raise ValueError("Unexpected protobuf response type")
            else:
                resp_msg.ParseFromString(resp_bytes)
        finally:
            metrics["parse_ms"] += (
                time.perf_counter() - parse_start
            ) * 1000
        metrics["successes"] += 1
        metrics["latencies_ms"].append(request_ms)
        return resp_msg

    except zmq.error.Again:
        if stage == "receive":
            metrics["timeouts"] += 1
        elif stage == "send":
            metrics["send_errors"] += 1
        else:
            metrics["other_errors"] += 1

        print(f"[!] {stage} failed: {label} on {machine}, port {port}")
        return None

    except Exception as error:
        if stage == "send":
            metrics["send_errors"] += 1
        else:
            metrics["other_errors"] += 1

        print(f"[!] {stage} error on {machine}:{port}: {error}")
        return None

    finally:
        zmq_socket.close(linger=0)

def percentile(sorted_values, percent):
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

def make_devices(number):
    hosts = [
        (3, "134.93.131.35"),
        (6, "134.93.128.228"),
        (7, "134.93.128.229"),
        #(8, "134.93.128.234"),
        (2, "134.93.130.214"),
        (9, "134.93.128.243"),
        (10, "134.93.129.24"),
        (11, "134.93.129.16"),
        (12, "134.93.131.161"),
        #(13, "134.93.129.22"),
        #(8, "134.93.128.234"),
        (14, "134.93.129.26"),
    ]

    devices = []

    for i in range(number):
        weber, ip = hosts[i % len(hosts)]
        dev = i // len(hosts) + 1

        devices.append({
            "tpc": weber,
            "dev": dev,
            "host": ip,
            "port": 5554 + dev,
        })

    return devices

CONTROL_FILE = (
    Path(__file__).resolve().parents[1]
    / "ignition_test_control.json"
)


def update_ignition_control(n, run_id, active):
    temporary = CONTROL_FILE.with_suffix(".tmp")

    temporary.write_text(json.dumps({
        "N": n,
        "run_id": run_id,
        "active": active,
    }))

    os.replace(temporary, CONTROL_FILE)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--devices", type=int, required=True)
    parser.add_argument("--warmup", type=float, default=30)
    args = parser.parse_args()

    if args.cycles < 1:
        parser.error("--cycles must be at least 1")

    if not 1 <= args.devices <= 1000:
        parser.error("--devices must be between 1 and 1000")

    if args.warmup < 0:
        parser.error("--warmup must be nonnegative")


    import logging
    import traceback


    class TraceAttribute23(logging.Filter):
        shown = False

        def filter(self, record):
            message = record.getMessage()
            if (
                "Tried to read attribute '23'" in message
                and "but the attribute is missing" in message
            ):
                if not self.shown:
                    self.shown = True
                    pass
                    #print("\n--- Source of attribute 23 request ---")
                    #traceback.print_stack(limit=15)
                return False
            return True


    logging.getLogger("opcua.server.address_space").addFilter(
        TraceAttribute23()
    )

    
    server = Server() #Creates OPC UA server
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("ZMQ-Ignition Bridge Server")
    devices = make_devices(args.devices)
    idx = server.register_namespace("")
    objects = server.get_objects_node()
    # Initialize the ZMQ devices obsjects
    ZMQDS = {}
    #for zmqd_info in cfg.get_devices():
    for zmqd_info in devices:
        key = (zmqd_info["tpc"], zmqd_info["dev"])
        #print("HOST:", repr(zmqd_info["host"]), type(zmqd_info["host"]))
        #ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"], host="localhost", port=zmqd_info["port"])
        ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"], host=zmqd_info["host"], port=zmqd_info["port"],)
    # Initialize the nodes
    Nodes = {}
    for (tpc, izmq), zmqd in ZMQDS.items():
        Nodes[(tpc, izmq)] = {}
        zmq_obj = objects.add_object(idx, f"TPC{tpc}_ZMQD{izmq}")

        initialize_nodes(zmq_obj, idx, Nodes[(tpc, izmq)], zmqd.voltages, tpc, izmq)
        initialize_nodes(zmq_obj, idx, Nodes[(tpc, izmq)], zmqd.temperatures, tpc, izmq)


    server.start()
    print(f"Server started at {server.endpoint}")

    run_id = uuid.uuid4().hex
    update_ignition_control(args.devices, run_id, True)

    ########################
    process = psutil.Process()  # Monitor this bridge.
    process.cpu_percent(None)

    device_count = len(ZMQDS)
    variable_count = sum(
        len(node_list)
        for device_nodes in Nodes.values()
        for node_list in device_nodes.values()
    )

    filename = f"bridge_N{device_count}.csv"
    csv_file = open(filename, "x", newline="")
    writer = csv.writer(csv_file)

    writer.writerow([
        "time_utc",
        "cycle",
        "devices",
        "variables",
        "cycle_s",
        "cpu_percent",
        "ram_mb",
        "attempts",
        "successes",
        "timeouts",
        "send_errors",
        "other_errors",
        "failure_percent",
        "acquisitions_per_s",
        "mean_request_ms",
        "zmq_tx_payload_kB_s",
        "zmq_rx_payload_kB_s",
        "node_writes",
        "node_writes_per_s",
        "parse_total_ms",
        "update_total_ms",
        "request_median_ms",
        "request_p95_ms",
        "request_p99_ms",
    ])

    print("Saving diagnostics to:", filename)
    ########################

    try:
        count = 0
        warmup_start = time.perf_counter()
        warming_up = args.warmup > 0

        while count < args.cycles:
            metrics = reset_metrics()
            cycle_start = time.perf_counter()
            time.sleep(1)

            if warming_up:
                print(f"\n=== Warm-up; Ndevices: {device_count} ===")
            else:
                count += 1
                print(
                    f"\n=== cycle {count}/{args.cycles}; "
                    f"Ndevices: {device_count} ==="
                )

            for zmqd_info in devices:
                tpc = zmqd_info["tpc"]
                izmq = zmqd_info["dev"]
                port = zmqd_info["port"]
                host=zmqd_info["host"]
                #print("host"+str(host))
                wib_ob = ZMQDS[(tpc, izmq)]

                #time.sleep(0.1)
                resp = zmqd_request(host, port, zmq_em_pb2.GetSensors(), zmq_em_pb2.GetSensors, "Sensors", use_any_response=False)
                if resp is not None:
                    update_start = time.perf_counter()
                    try:
                        update_node(resp, Nodes, wib_ob)
                    finally:
                        metrics["update_ms"] += (
                            time.perf_counter() - update_start
                        ) * 1000
            if warming_up:
                elapsed = time.perf_counter() - warmup_start

                # Discard CPU readings from warm-up.
                process.cpu_percent(None)

                if elapsed >= args.warmup:
                    warming_up = False
                    print(
                        f"Warm-up finished after {elapsed:.1f} s. "
                        "Starting measured cycles."
                    )

                continue

            cycle_s = time.perf_counter() - cycle_start
            cycle_s = time.perf_counter() - cycle_start
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
            sorted_latencies = sorted(metrics["latencies_ms"])
            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                count,
                device_count,
                variable_count,
                round(cycle_s, 3),
                cpu,
                round(ram_mb, 2),
                metrics["attempts"],
                metrics["successes"],
                metrics["timeouts"],
                metrics["send_errors"],
                metrics["other_errors"],
                failure_percent,
                metrics["successes"] / cycle_s,
                mean_request_ms,
                metrics["tx_bytes"] / 1000 / cycle_s,
                metrics["rx_bytes"] / 1000 / cycle_s,
                metrics["node_writes"],
                metrics["node_writes"] / cycle_s,
                metrics["parse_ms"],
                metrics["update_ms"],
                percentile(sorted_latencies, 50),
                percentile(sorted_latencies, 95),
                percentile(sorted_latencies, 99),
            ])
            csv_file.flush()

            print(
                f"Cycle {count}/{args.cycles}: "
                f"{cycle_s:.2f} s | CPU {cpu:.1f}% | RAM {ram_mb:.1f} MB"
            )


    except KeyboardInterrupt:
        pass
    finally:
        try:
            update_ignition_control(args.devices, run_id, False)
        finally:
            try:
                csv_file.close()
            finally:
                server.stop()
                print("Server stopped")
