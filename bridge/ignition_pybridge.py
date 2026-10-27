import sys
sys.path.insert(0, "..")
import time
from opcua import Server, ua
import zmq
import wib_pb2
from wib_config import WIBConfig
from wib_sensor_config import WIBSensorConfig
from devices_config import DevicesConfig
from sensor_readers import IPMIReader, SNMPReader, SCPIReader

context = zmq.Context()

cfg = WIBConfig()
print("Loaded WIBs from config:")
for wib in cfg.get_wibs():
    print(f"  TPC{wib['tpc']} WIB{wib['wib']} -> port {wib['port']}")

devices_cfg = DevicesConfig()
print("Loaded IPMI devices from config:")
for dev in devices_cfg.get_ipmi_devices():
    print(f"  {dev['id']} -> {dev['host']}:{dev.get('port', 623)} ({len(dev.get('sensors', []))} sensors)")
print("Loaded SNMP devices from config:")
for dev in devices_cfg.get_snmp_devices():
    print(f"  {dev['id']} -> {dev['host']}:{dev.get('port', 161)} ({len(dev.get('sensors', []))} sensors)")
print("Loaded SCPI devices from config:")
for dev in devices_cfg.get_scpi_devices():
    print(f"  {dev['id']} -> {dev['host']}:{dev.get('port', 5025)} ({len(dev.get('sensors', []))} sensors)")

# Which WIB protobuf fields become OPC UA nodes, and how many array
# elements each one gets, is config-driven (wib_sensors.yaml) rather than
# hardcoded - see that file to add/remove a WIB sensor.
wib_sensor_cfg = WIBSensorConfig()
SENSOR_MAP_V = wib_sensor_cfg.get_voltages()
SENSOR_MAP_Temp = wib_sensor_cfg.get_temperatures()
VERSION_MAP = wib_sensor_cfg.get_version()
TIMESTAMP_MAP = wib_sensor_cfg.get_timestamp()
TIMING_STATUS_MAP = wib_sensor_cfg.get_timing_status()
print("Loaded WIB sensor fields from config:")
print(f"  voltages={len(SENSOR_MAP_V)} temperatures={len(SENSOR_MAP_Temp)} "
      f"version={len(VERSION_MAP)} timestamp={len(TIMESTAMP_MAP)} "
      f"timing_status={len(TIMING_STATUS_MAP)}")


class WIB:
    def __init__(self, tpc, wib, host, port):
        self.tpc = tpc
        self.wib = wib
        self.host = host
        self.port = port
        self.voltages = {name: [0.0] * n for name, n in SENSOR_MAP_V.items()}
        self.temperatures = {name: [0.0] * n for name, n in SENSOR_MAP_Temp.items()}
        self.version = {name: [""] * n for name, n in VERSION_MAP.items()}
        self.timestamp = {name: [0] * n for name, n in TIMESTAMP_MAP.items()}
        self.timingstatus = {name: [0] * n for name, n in TIMING_STATUS_MAP.items()}


def initialize_nodes(parent, idx, nodes, mapping, ptc, iwib, label):
    """Create one OPC UA object + variables per entry in `mapping`, under `parent`."""
    for name, values in mapping.items():
        obj = parent.add_object(idx, name)
        nodes[name] = []

        n = len(values) 
        for i in range(len(values)):
            leaf = name if n == 1 else f"{name}_{i}"
            nodeid = ua.NodeId(f"wib_{iwib}.{label}.{leaf}", idx)
            var = obj.add_variable(nodeid, f"{name}_{i}", values[i])
            nodes[name].append(var)

    return nodes

def update_node(resp_msg, nodes_by_wib, wib):
    """Copy the fields of a protobuf response into the OPC UA nodes for one WIB."""
    wib_nodes = nodes_by_wib[(wib.tpc, wib.wib)]

    for name in wib_nodes.keys():
        if not hasattr(resp_msg, name):
            continue

        value = getattr(resp_msg, name)

        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            for i, v in enumerate(value):
                if i < len(wib_nodes[name]):
                    wib_nodes[name][i].set_value(v)
        elif len(wib_nodes[name]) > 0:
            wib_nodes[name][0].set_value(value)

    return nodes_by_wib


def initialize_simple_nodes(parent, idx, device_id, sensor_names):
    """Create one OPC UA variable per sensor name, flat under `parent`.

    Used for IPMI/SNMP devices, whose sensors are a flat name->value list
    from config rather than the WIB's fixed protobuf-shaped fields.
    """
    nodes = {}
    for name in sensor_names:
        nodeid = ua.NodeId(f"{device_id}/{name}", idx)
        var = parent.add_variable(nodeid, name, 0.0)
        nodes[name] = var
    return nodes


def update_simple_nodes(nodes, values):
    """Copy a {sensor_name: value} dict from a reader into its OPC UA nodes."""
    for name, value in values.items():
        node = nodes.get(name)
        if node is not None:
            node.set_value(value)


def wib_request(port, req_msg, resp_msg_class, label):
    """
    Send a telemetry request to the WIB on `port` and return the parsed response,
    or None on timeout/error. Opens a fresh REQ socket per call so a single
    slow/dead backend can't desync the REQ/REP state for the others.
    """
    if type(req_msg) not in (
        wib_pb2.GetSWVersion, wib_pb2.GetTimingStatus,
        wib_pb2.GetSensors, wib_pb2.GetTimestamp,
    ):
        raise ValueError("The monitoring bridge only accepts telemetry requests")

    wib_socket = context.socket(zmq.REQ)
    try:
        wib_socket.connect(f"tcp://localhost:{port}")
        wib_socket.setsockopt(zmq.RCVTIMEO, 2000)

        command = wib_pb2.Command()
        command.cmd.Pack(req_msg)
        wib_socket.send(command.SerializeToString(), flags=zmq.DONTWAIT)

        resp_bytes = wib_socket.recv()

        resp_msg = resp_msg_class()
        resp_msg.ParseFromString(resp_bytes)

        return resp_msg
    except zmq.error.Again:
        print(f" [!] Timeout: {label} request timed out on port {port}")
        return None
    except Exception as e:
        print(f" [!] Error reading {label} on port {port}: {e}")
        return None
    finally:
        wib_socket.close(linger=0)


def poll_wib(wib, nodes_by_wib):
    """Read telemetry and update the bridge's own OPC-UA values."""
    for request, reply_type, label in (
        (wib_pb2.GetSWVersion, wib_pb2.GetSWVersion.Version, "Version"),
        (wib_pb2.GetTimingStatus, wib_pb2.GetTimingStatus.TimingStatus, "Timing Status"),
        (wib_pb2.GetSensors, wib_pb2.GetSensors.Sensors, "Sensors"),
        (wib_pb2.GetTimestamp, wib_pb2.GetTimestamp.Timestamp, "Timestamp"),
    ):
        reply = wib_request(wib.port, request(), reply_type, label)
        if reply is not None:
            update_node(reply, nodes_by_wib, wib)


if __name__ == "__main__":
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("WIB-Ignition Bridge Server")

    idx = server.register_namespace("OPCUASERVER")
    objects = server.get_objects_node()

    WIBS = {}
    for wib_info in cfg.get_wibs():
        key = (wib_info["tpc"], wib_info["wib"])
        WIBS[key] = WIB(tpc=wib_info["tpc"], wib=wib_info["wib"], host="localhost", port=wib_info["port"])

    Nodes = {}
    for (tpc, iwib), wib in WIBS.items():
        Nodes[(tpc, iwib)] = {}
        wib_obj = objects.add_object(idx, f"WIB{iwib}")

        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.voltages, tpc, iwib, "sensors")
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.temperatures, tpc, iwib, "sensors")
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.version, tpc, iwib, "sw_version")
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.timestamp, tpc, iwib, "timestamp")
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.timingstatus, tpc, iwib, "timing")

    # IPMI/SNMP devices are entirely config-driven (devices.yaml): each
    # entry there becomes one OPC UA object with one variable per listed
    # sensor. Adding a sensor only requires editing the config.
    Pollers = []  # list of {"reader", "nodes", "poll_interval", "next_poll"}

    for dev in devices_cfg.get_ipmi_devices():
        dev_id = dev["id"]
        sensor_names = dev.get("sensors", [])
        reader = IPMIReader(
            host=dev["host"],
            port=dev.get("port", 623),
            username=dev.get("username", ""),
            password=dev.get("password", ""),
            priv_level=dev.get("priv_level", "administrator"),
            sensors=sensor_names,
        )
        dev_obj = objects.add_object(idx, dev_id)
        nodes = initialize_simple_nodes(dev_obj, idx, dev_id, sensor_names)
        Pollers.append({
            "reader": reader,
            "nodes": nodes,
            "poll_interval": dev.get("poll_interval", 5),
            "next_poll": 0.0,
        })

    for dev in devices_cfg.get_snmp_devices():
        dev_id = dev["id"]
        sensors = dev.get("sensors", [])
        sensor_names = [s["name"] for s in sensors]
        reader = SNMPReader(
            host=dev["host"],
            port=dev.get("port", 161),
            community=dev.get("community", "public"),
            version=dev.get("version", "2c"),
            sensors=sensors,
        )
        dev_obj = objects.add_object(idx, dev_id)
        nodes = initialize_simple_nodes(dev_obj, idx, dev_id, sensor_names)
        Pollers.append({
            "reader": reader,
            "nodes": nodes,
            "poll_interval": dev.get("poll_interval", 5),
            "next_poll": 0.0,
        })

    for dev in devices_cfg.get_scpi_devices():
        dev_id = dev["id"]
        sensors = dev.get("sensors", [])
        sensor_names = [s["name"] for s in sensors]
        reader = SCPIReader(
            host=dev["host"],
            port=dev.get("port", 5025),
            sensors=sensors,
        )
        dev_obj = objects.add_object(idx, dev_id)
        nodes = initialize_simple_nodes(dev_obj, idx, dev_id, sensor_names)
        Pollers.append({
            "reader": reader,
            "nodes": nodes,
            "poll_interval": dev.get("poll_interval", 5),
            "next_poll": 0.0,
        })

    server.start()
    print(f"Server started at {server.endpoint}")

    try:
        count = 0
        while True:
            time.sleep(1)
            count += 1
            print(f"\n=== cycle {count} ===")

            for wib_info in cfg.get_wibs():
                tpc = wib_info["tpc"]
                iwib = wib_info["wib"]
                wib_ob = WIBS[(tpc, iwib)]
                poll_wib(wib_ob, Nodes)

            now = time.time()
            for poller in Pollers:
                if now < poller["next_poll"]:
                    continue
                values = poller["reader"].read()
                update_simple_nodes(poller["nodes"], values)
                poller["next_poll"] = now + poller["poll_interval"]

    except KeyboardInterrupt:
        pass
    finally:
        for poller in Pollers:
            close = getattr(poller["reader"], "close", None)
            if close is not None:
                close()
        server.stop()
        context.term()
        print("Server stopped")
