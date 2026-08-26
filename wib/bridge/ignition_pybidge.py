import sys
sys.path.insert(0, "..")
import time
from opcua import Server, ua
import zmq
from google.protobuf.any_pb2 import Any
import wib_pb2
from wib_config import WIBConfig
from wib_sensor_config import WIBSensorConfig
from devices_config import DevicesConfig
from sensor_readers import IPMIReader, SNMPReader, SCPIReader

context = zmq.Context()
socket = context.socket(zmq.REQ)

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
PEEK_MAP = wib_sensor_cfg.get_peek()
print("Loaded WIB sensor fields from config:")
print(f"  voltages={len(SENSOR_MAP_V)} temperatures={len(SENSOR_MAP_Temp)} "
      f"version={len(VERSION_MAP)} timestamp={len(TIMESTAMP_MAP)} "
      f"timing_status={len(TIMING_STATUS_MAP)} peek={len(PEEK_MAP)}")


class WIB:
    def __init__(self, tpc, wib, host, port):
        self.tpc = tpc
        self.wib = wib
        self.host = host
        self.port = port
        self.voltages = {name: [0.0] * n for name, n in SENSOR_MAP_V.items()}
        self.temperatures = {name: [0.0] * n for name, n in SENSOR_MAP_Temp.items()}
        self.version = {name: [0.0] * n for name, n in VERSION_MAP.items()}
        self.timestamp = {name: [0.0] * n for name, n in TIMESTAMP_MAP.items()}
        self.timingstatus = {name: [0.0] * n for name, n in TIMING_STATUS_MAP.items()}
        self.peek = {name: [0.0] * n for name, n in PEEK_MAP.items()}


def initialize_nodes(parent, idx, nodes, mapping, tpc, iwib):
    """Create one OPC UA object + variables per entry in `mapping`, under `parent`."""
    for name, values in mapping.items():
        obj = parent.add_object(idx, name)
        nodes[name] = []

        init_value = 0 if name == "addr" else 0.0

        for i in range(len(values)):
            nodeid = ua.NodeId(f"TPC{tpc}/WIB{iwib}/{name}/{i}", idx)
            var = obj.add_variable(nodeid, f"{name}_{i}", init_value)
            var.set_writable()
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
        var.set_writable()
        nodes[name] = var
    return nodes


def update_simple_nodes(nodes, values):
    """Copy a {sensor_name: value} dict from a reader into its OPC UA nodes."""
    for name, value in values.items():
        node = nodes.get(name)
        if node is not None:
            node.set_value(value)


def send_power_command(config):
    """Send a PowerWIB command over the shared REQ socket. Not wired into the polling loop."""
    msg = wib_pb2.PowerWIB()
    msg.femb0 = config["femb0"]
    msg.femb1 = config["femb1"]
    msg.femb2 = config["femb2"]
    msg.femb3 = config["femb3"]
    msg.cold = config["cold"]
    msg.stage = config["stage"]

    any_msg = Any()
    any_msg.Pack(msg)
    socket.send(any_msg.SerializeToString())

    resp_bytes = socket.recv()
    resp_any = Any()
    resp_any.ParseFromString(resp_bytes)

    status = wib_pb2.Status()
    resp_any.Unpack(status)
    return status


def wib_request(port, req_msg, resp_msg_class, label, use_any_response=True):
    """
    Send `req_msg` to the WIB backend on `port` and return the parsed response,
    or None on timeout/error. Opens a fresh REQ socket per call so a single
    slow/dead backend can't desync the REQ/REP state for the others.
    """
    wib_socket = context.socket(zmq.REQ)
    try:
        wib_socket.connect(f"tcp://localhost:{port}")
        wib_socket.setsockopt(zmq.RCVTIMEO, 2000)

        req_any = Any()
        req_any.Pack(req_msg)
        wib_socket.send(req_any.SerializeToString(), flags=zmq.DONTWAIT)

        resp_bytes = wib_socket.recv()

        resp_msg = resp_msg_class()
        if use_any_response:
            resp_any = Any()
            resp_any.ParseFromString(resp_bytes)
            resp_any.Unpack(resp_msg)
        else:
            # The Sensors backend replies with a raw serialized message,
            # not wrapped in google.protobuf.Any.
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


if __name__ == "__main__":
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("WIB-Ignition Bridge Server")

    idx = server.register_namespace("")
    objects = server.get_objects_node()

    WIBS = {}
    for wib_info in cfg.get_wibs():
        key = (wib_info["tpc"], wib_info["wib"])
        WIBS[key] = WIB(tpc=wib_info["tpc"], wib=wib_info["wib"], host="localhost", port=wib_info["port"])

    Nodes = {}
    for (tpc, iwib), wib in WIBS.items():
        Nodes[(tpc, iwib)] = {}
        wib_obj = objects.add_object(idx, f"WIB{iwib}")

        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.voltages, tpc, iwib)
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.temperatures, tpc, iwib)
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.version, tpc, iwib)
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.timestamp, tpc, iwib)
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.timingstatus, tpc, iwib)
        initialize_nodes(wib_obj, idx, Nodes[(tpc, iwib)], wib.peek, tpc, iwib)

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
                port = wib_info["port"]
                wib_ob = WIBS[(tpc, iwib)]

                resp = wib_request(port, wib_pb2.GetSWVersion(), wib_pb2.GetSWVersion.Version, "Version")
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

                resp = wib_request(port, wib_pb2.GetTimingStatus(), wib_pb2.GetTimingStatus.TimingStatus, "Timing Status")
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

                time.sleep(0.1)
                resp = wib_request(port, wib_pb2.GetSensors(), wib_pb2.GetSensors.Sensors, "Sensors", use_any_response=False)
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

                resp = wib_request(port, wib_pb2.Peek(), wib_pb2.Peek, "Peek")
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

                poke_msg = wib_pb2.Poke()
                if count % 2 == 0:
                    poke_msg.addr = 0x0000
                    poke_msg.value = count
                else:
                    poke_msg.addr = 0x0004
                    poke_msg.value = count
                if count == 10:
                    poke_msg.addr = 0xDEAD
                    poke_msg.value = 1
                wib_request(port, poke_msg, wib_pb2.RegValue, "Poke")

                resp = wib_request(port, wib_pb2.Peek(), wib_pb2.Peek, "Peek (post-poke)")
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

                resp = wib_request(port, wib_pb2.GetTimestamp(), wib_pb2.GetTimestamp.Timestamp, "Timestamp")
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

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
        print("Server stopped")
