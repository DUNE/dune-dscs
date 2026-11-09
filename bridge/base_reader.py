"""Common interface for every protocol reader polled by ignition_pybridge.py.

A reader only has to implement `read()`, returning {metric_name: value}.
`value` is either a scalar or a list (one entry per array element).
The bridge then pushes those values into OPC UA with `update_nodes()`,
so the main loop never needs to know which protocol a device speaks.
"""


class BaseReader:
    protocol = "BASE"

    def read(self):
        """Return {metric_name: value or [values]}; {} if nothing could be read."""
        raise NotImplementedError

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
