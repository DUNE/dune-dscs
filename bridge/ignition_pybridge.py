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
    server = Server() 
    server.set_endpoint(endpoint.ignition_endpoint)
    server.set_server_name(endpoint.server_name)
    idx = server.register_namespace(endpoint.register_namespace)
    objects = server.get_objects_node()

   # Initialization.
    protocols = ["ZMQ"] # Allowd devices ZMQ. IPMI, SNMP
    devices = DEVICES(devices_protocols = protocols, objects =  objects, idx = idx)
    devices.initialize_devices()
    Pollers = devices.pollers  # list of {"reader", "nodes", "poll_interval", "next_poll"}

    server.start()
    print(f"Server started at {server.endpoint}")

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
        server.stop()
        print("Server stopped")
