"""Common interface for every protocol reader polled by ignition_pybridge.py.

A reader only has to implement `read()`, returning {metric_name: value}.
`value` is either a scalar or a list (one entry per array element).
The bridge then pushes those values into OPC UA with `update_nodes()`,
so the main loop never needs to know which protocol a device speaks.

For concurrent polling the bridge awaits `read_async()`. By default it runs
the blocking `read()` in a worker thread, so any reader works unchanged;
readers whose library is natively async (ZMQ, SNMP) override it.
"""
import asyncio


class BaseReader:
    protocol = "BASE"

    @property
    def label(self):
        """Short name for log messages."""
        name = getattr(self, "dev", None) or getattr(self, "host", "?")
        return f"{self.protocol}:{name}"

    def read(self):
        """Return {metric_name: value or [values]}; {} if nothing could be read."""
        raise NotImplementedError

    async def read_async(self):
        """Non-blocking read. Default: run `read()` in a thread."""
        return await asyncio.to_thread(self.read)

    def close(self):
        """Release sockets/sessions. Optional for readers that hold none."""

    def update_nodes(self, nodes, values):
        """Copy `values` into `nodes` ({metric_name: [opcua_variable, ...]})."""
        if not values:
            return
        for name, value in values.items():
            node_list = nodes.get(name)
            if not node_list:
                continue
            if isinstance(value, (list, tuple)):
                for node, v in zip(node_list, value):
                    node.set_value(v)
            else:
                node_list[0].set_value(value)
