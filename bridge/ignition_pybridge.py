import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "wib", "protobuf"))
os.chdir(HERE)  # YAML configs are opened with relative paths
import time
from opcua import Server, ua
import zmq
from google.protobuf.any_pb2 import Any
import wib_pb2
from endpoint_config import ENDPOINT
from Devices import DEVICES 


if __name__ == "__main__":
    #Server configuration
    endpoint = ENDPOINT()
    bridge_server = Server() 
    bridge_server.set_endpoint(endpoint.bridge_endpoint_info.bridge_endpoint)
    bridge_server.set_server_name(endpoint.bridge_endpoint_info.server_name)
    idx = bridge_server.register_namespace(endpoint.bridge_endpoint_info.register_namespace)
    objects = bridge_server.get_objects_node()

   # Initialization.
    protocols = ["ZMQ"] # Allowd devices ZMQ. IPMI, SNMP
    devices = DEVICES(devices_protocols = protocols, objects =  objects, idx = idx)
    Pollers = devices.pollers  # list of {"reader", "nodes", "poll_interval", "next_poll"}

    bridge_server.start()
    print(f"Server started at {bridge_server.endpoint}")

    try:
        count = 0
        while True:
            time.sleep(5)
            count += 1
            print(f"\n=== cycle {count} ===")
            now = time.time()
            for poller in Pollers:
                if now < poller["next_poll"]:
                    continue
                values = poller["reader"].read()
                print (values)
                if values:
                    poller["reader"].update_nodes(poller["nodes"], values)
                poller["next_poll"] = now + poller["poll_interval"]
    except KeyboardInterrupt:
        pass
    finally:
        for poller in Pollers:
            close = getattr(poller["reader"], "close", None)
            if close is not None:
                close()
        bridge_server.stop()
        print("Server stopped")
