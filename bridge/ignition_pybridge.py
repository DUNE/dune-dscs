import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "wib", "protobuf"))
os.chdir(HERE)  # YAML configs are opened with relative paths
import asyncio
import time
from opcua import Server
from endpoint_config import ENDPOINT
from Devices import DEVICES

VERBOSE = False  # True: print every value read, not just a one-line summary


async def poll_device(poller):
    """Poll one device forever on its own poll_interval.

    Each device runs in its own task, so a slow or unreachable device only
    delays itself; the others keep their cadence.
    """
    reader = poller["reader"]
    interval = poller["poll_interval"]
    while True:
        start = time.monotonic()
        try:
            values = await reader.read_async()
        except Exception as e:  # a reader bug must not kill the other tasks
            print(f" [!] {reader.label}: {e}")
            values = {}
        if values:
            reader.update_nodes(poller["nodes"], values)
        elapsed = time.monotonic() - start
        print(f"{reader.label}: {len(values)} metrics in {elapsed:.3f}s")
        if VERBOSE:
            print(values)
        await asyncio.sleep(max(0.0, interval - elapsed))


async def main(pollers):
    tasks = [asyncio.create_task(poll_device(p)) for p in pollers]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    #Server configuration
    endpoint = ENDPOINT()
    bridge_server = Server()
    bridge_server.set_endpoint(endpoint.bridge_endpoint_info.bridge_endpoint)
    bridge_server.set_server_name(endpoint.bridge_endpoint_info.server_name)
    idx = bridge_server.register_namespace(endpoint.bridge_endpoint_info.register_namespace)
    objects = bridge_server.get_objects_node()

    # Initialization.
    protocols = ["ZMQ"]  # any of: ZMQ, IPMI, SNMP, SCPI
    devices = DEVICES(devices_protocols=protocols, objects=objects, idx=idx)
    Pollers = devices.pollers  # list of {"reader", "nodes", "poll_interval", "next_poll"}

    bridge_server.start()
    print(f"Server started at {bridge_server.endpoint}")

    try:
        asyncio.run(main(Pollers))
    except KeyboardInterrupt:
        pass
    finally:
        for poller in Pollers:
            poller["reader"].close()
        bridge_server.stop()
        print("Server stopped")
