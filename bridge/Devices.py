"""Builds one reader + its OPC UA nodes per configured device, for any protocol.

Every entry appended to `self.pollers` has the same shape, so the main loop
just calls `reader.read()` / `reader.update_nodes()` regardless of protocol:
    {"reader": BaseReader, "nodes": {name: [var, ...]}, "poll_interval": s, "next_poll": t}
"""
import yaml
from opcua import ua

from devices_config import DevicesConfig
from zmq_readers import DEFAULTS, ZMQReader, load_device_type


class DEVICES:
    def __init__(self, devices_protocols, objects, idx,
                 zmq_devices_file="zmq_devices.yaml",
                 zmq_metrics_file="zmq_metrics.yaml",
                 devices_file="devices.yaml"):
        self.protocols = [p.upper() for p in devices_protocols]
        self.objects = objects
        self.idx = idx
        self.zmq_devices_file = zmq_devices_file
        self.zmq_metrics_file = zmq_metrics_file
        self.devices_file = devices_file
        self.pollers = []

    def initialize_devices(self):
        builders = {
            "ZMQ": self._init_zmq,
            "IPMI": self._init_ipmi,
            "SNMP": self._init_snmp,
            "SCPI": self._init_scpi,
        }
        for protocol in self.protocols:
            if protocol not in builders:
                raise ValueError(f"Unknown protocol '{protocol}', use one of {list(builders)}")
            print(f"Initializing {protocol} devices ...")
            builders[protocol]()

    def _add_poller(self, reader, nodes, poll_interval):
        self.pollers.append({
            "reader": reader,
            "nodes": nodes,
            "poll_interval": poll_interval,
            "next_poll": 0.0,
        })

    # ---------------- ZMQ ----------------
    def _init_zmq(self):
        with open(self.zmq_devices_file) as f:
            devs_config = yaml.safe_load(f) or {}
        with open(self.zmq_metrics_file) as f:
            metrics_config = yaml.safe_load(f) or {}

        for dev_type, dev_list in devs_config.items():
            if dev_type not in metrics_config:
                raise KeyError(f"'{dev_type}' is in {self.zmq_devices_file} "
                               f"but has no entry in {self.zmq_metrics_file}")
            envelope, messages = load_device_type(metrics_config[dev_type])

            for dev in dev_list:
                dev_name = f"{dev_type}_{dev['ID_n']}"
                reader = ZMQReader(
                    dev=dev_name,
                    tpc=dev.get("tpc"),
                    host=dev["host"],
                    port=dev["port"],
                    envelope=envelope,
                    messages=messages,
                    timeout_ms=dev.get("timeout_ms", 2000),
                )
                dev_obj = self.objects.add_object(self.idx, dev_name)
                nodes = self._init_array_nodes(dev_obj, "ZMQ", dev_name, messages)
                self._add_poller(reader, nodes, dev.get("poll_interval", 5))

    def _init_array_nodes(self, parent, protocol, dev_name, messages):
        """One folder per field, one variable per element: <field>/<field>_<i>."""
        nodes = {}
        for spec in messages.values():
            for name, fspec in spec["fields"].items():
                obj = parent.add_object(self.idx, name)
                init_value = DEFAULTS[fspec["type"]]
                nodes[name] = []
                for i in range(fspec["size"]):
                    nodeid = ua.NodeId(f"{protocol}/{dev_name}/{name}/{i}", self.idx)
                    var = obj.add_variable(nodeid, f"{name}_{i}", init_value)
                    var.set_writable()
                    nodes[name].append(var)
        return nodes

    # ------------- IPMI / SNMP / SCPI -------------
    # sensor_readers is imported lazily so a ZMQ-only bridge does not need
    # pyipmi / pysnmp installed.
    def _init_ipmi(self):
        from sensor_readers import IPMIReader
        for dev in DevicesConfig(self.devices_file).get_ipmi_devices():
            names = list(dev.get("sensors", []))
            reader = IPMIReader(
                host=dev["host"],
                port=dev.get("port", 623),
                username=dev.get("username", ""),
                password=dev.get("password", ""),
                priv_level=dev.get("priv_level", "administrator"),
                sensors=names,
            )
            self._add_simple_device(reader, "IPMI", dev, names)

    def _init_snmp(self):
        from sensor_readers import SNMPReader
        for dev in DevicesConfig(self.devices_file).get_snmp_devices():
            sensors = dev.get("sensors", [])
            reader = SNMPReader(
                host=dev["host"],
                port=dev.get("port", 161),
                community=dev.get("community", "public"),
                version=dev.get("version", "2c"),
                sensors=sensors,
            )
            self._add_simple_device(reader, "SNMP", dev, [s["name"] for s in sensors])

    def _init_scpi(self):
        from sensor_readers import SCPIReader
        for dev in DevicesConfig(self.devices_file).get_scpi_devices():
            sensors = dev.get("sensors", [])
            reader = SCPIReader(
                host=dev["host"],
                port=dev.get("port", 5025),
                sensors=sensors,
            )
            self._add_simple_device(reader, "SCPI", dev, [s["name"] for s in sensors])

    def _add_simple_device(self, reader, protocol, dev, sensor_names):
        """Flat layout: one scalar variable per sensor directly under the device."""
        dev_id = dev["id"]
        dev_obj = self.objects.add_object(self.idx, dev_id)
        nodes = {}
        for name in sensor_names:
            nodeid = ua.NodeId(f"{protocol}/{dev_id}/{name}", self.idx)
            var = dev_obj.add_variable(nodeid, name, 0.0)
            var.set_writable()
            nodes[name] = [var]
        self._add_poller(reader, nodes, dev.get("poll_interval", 1))
