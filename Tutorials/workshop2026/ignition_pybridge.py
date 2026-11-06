#### Comments: reflect changes for the new accessible device names 

import sys
sys.path.insert(0, "..")
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


context = zmq.Context()
socket = context.socket(zmq.REQ) #request socket

cfg = ZMQDevicesConfig()
#print("Loaded WIBs from config:")
#for wib in cfg.get_devices():
#    print(f"  TPC{wib['tpc']} WIB{wib['wib']} -> port {wib['port']}")


zmq_sensor_cfg = ZMQSensorConfig() ## load sensor configurations and separate variable sin labels 
SENSOR_MAP_V = zmq_sensor_cfg.get_voltages()
SENSOR_MAP_Temp = zmq_sensor_cfg.get_temperatures()
#print("Loaded WIB sensor fields from config:")

class ZMQ:
    def __init__(self, tpc, dev, host, port): #### def __init__(self, tpc, dev, host, port, name):
        self.tpc = tpc
        self.dev = dev
        self.host = host
        self.port = port
        ### self.name = name
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


def zmqd_request(host, port, req_msg, resp_msg_class, label, use_any_response=True):
    """
    Send `req_msg` to the WIB backend on `port` and return the parsed response,
    or None on timeout/error. Opens a fresh REQ socket per call so a single
    slow/dead backend can't desync the REQ/REP state for the others.
    """
    zmq_socket = context.socket(zmq.REQ)
    machine = WEBER_NAMES.get(host, host)
    try:
        #zmq_socket.connect(f"tcp://localhost:{port}")
        zmq_socket.connect(f"tcp://{host}:{port}")
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
        print(f"[!] Timeout: {label} on {machine}, port {port}")
        return None
    except Exception as e:
        print(f"[!] Error reading {label} on {machine}, port {port}: {e}")
        return None
    finally:
        zmq_socket.close(linger=0)


if __name__ == "__main__":
    server = Server() #Creates OPC UA server
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("ZMQ-Ignition Bridge Server")

    idx = server.register_namespace("")
    objects = server.get_objects_node()
    # Initialize the ZMQ devices obsjects
    ZMQDS = {}
    for zmqd_info in cfg.get_devices():
        key = (zmqd_info["tpc"], zmqd_info["dev"])
        #print("HOST:", repr(zmqd_info["host"]), type(zmqd_info["host"]))
        #ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"], host="localhost", port=zmqd_info["port"])
        ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"], host=zmqd_info["host"], port=zmqd_info["port"],)
        ### ZMQDS[key] = ZMQ(tpc=zmqd_info["tpc"], dev=zmqd_info["dev"],host=zmqd_info["host"],port=zmqd_info["port"],name=zmqd_info["name"],)
    # Initialize the nodes
    Nodes = {}
    for (tpc, izmq), zmqd in ZMQDS.items():
        Nodes[(tpc, izmq)] = {}
        zmq_obj = objects.add_object(idx, f"TPC{tpc}_ZMQD{izmq}")
        ###  zmq_obj = objects.add_object(idx, zmqd.name)

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
                host=zmqd_info["host"]
                #print("host"+str(host))
                wib_ob = ZMQDS[(tpc, izmq)]

                #time.sleep(0.1)
                resp = zmqd_request(host, port, zmq_em_pb2.GetSensors(), zmq_em_pb2.GetSensors, "Sensors", use_any_response=False)
                if resp is not None:
                    update_node(resp, Nodes, wib_ob)


    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("Server stopped")
