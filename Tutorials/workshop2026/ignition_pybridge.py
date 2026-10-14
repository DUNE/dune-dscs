import sys
sys.path.insert(0, "..")
import time
from opcua import Server, ua
import zmq
from google.protobuf.any_pb2 import Any
import zmq_em_pb2
from zmq_devices_config import ZMQDevicesConfig
from zmq_sensor_config import ZMQSensorConfig

context = zmq.Context()
socket = context.socket(zmq.REQ)

cfg = ZMQDevicesConfig()
#print("Loaded WIBs from config:")
#for wib in cfg.get_devices():
#    print(f"  TPC{wib['tpc']} WIB{wib['wib']} -> port {wib['port']}")


# Which WIB protobuf fields become OPC UA nodes, and how many array
# elements each one gets, is config-driven (wib_sensors.yaml) rather than
# hardcoded - see that file to add/remove a WIB sensor.
zmq_sensor_cfg = ZMQSensorConfig()
SENSOR_MAP_V = zmq_sensor_cfg.get_voltages()
SENSOR_MAP_Temp = zmq_sensor_cfg.get_temperatures()
print("Loaded WIB sensor fields from config:")

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
        elif len(zmq_nodes[name]) > 0:
            zmq_nodes[name][0].set_value(value)

    return nodes_by_zmq


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


def zmqd_request(port, req_msg, resp_msg_class, label, use_any_response=True):
    """
    Send `req_msg` to the WIB backend on `port` and return the parsed response,
    or None on timeout/error. Opens a fresh REQ socket per call so a single
    slow/dead backend can't desync the REQ/REP state for the others.
    """
    zmq_socket = context.socket(zmq.REQ)
    try:
        zmq_socket.connect(f"tcp://localhost:{port}")
        zmq_socket.setsockopt(zmq.RCVTIMEO, 2000)

        req_any = Any()
        req_any.Pack(req_msg)
        zmq_socket.send(req_any.SerializeToString(), flags=zmq.DONTWAIT)

        resp_bytes = zmq_socket.recv()

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
        zmq_socket.close(linger=0)


if __name__ == "__main__":
    server = Server()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("ZMQ-Ignition Bridge Server")

    idx = server.register_namespace("")
    objects = server.get_objects_node()

    ZMQDS = {}
    for zmqd_info in cfg.get_devices():
        key = (zmqd_info["tpc"], zmqd_info["dev"])
        ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"], host="localhost", port=zmqd_info["port"])

    Nodes = {}
    for (tpc, izmq), zmqd in ZMQDS.items():
        Nodes[(tpc, izmq)] = {}
        zmq_obj = objects.add_object(idx, f"ZMQD{izmq}")

        initialize_nodes(zmq_obj, idx, Nodes[(tpc, izmq)], zmqd.voltages, tpc, izmq)
        initialize_nodes(zmq_obj, idx, Nodes[(tpc, izmq)], zmqd.temperatures, tpc, izmq)


    server.start()
    print(f"Server started at {server.endpoint}")

    try:
        count = 0
        while True:
            time.sleep(1)
            count += 1
            print(f"\n=== cycle {count} ===")

            for zmqd_info in cfg.get_devices():
                tpc = zmqd_info["tpc"]
                izmq = zmqd_info["dev"]
                port = zmqd_info["port"]
                wib_ob = ZMQDS[(tpc, izmq)]

                #time.sleep(0.1)
                resp = zmqd_request(port, zmq_em_pb2.GetSensors(), zmq_em_pb2.GetSensors, "Sensors", use_any_response=False)
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)

            now = time.time()

    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("Server stopped")
