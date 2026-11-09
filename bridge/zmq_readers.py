"""Config-driven ZMQ/protobuf reader.

Everything protocol-specific (which protobuf messages to send, how the reply
is wrapped, which fields to keep) comes from zmq_metrics.yaml, so new
device types or messages only need a config change. See that file for the
format.
"""
import importlib

import zmq
from google.protobuf.any_pb2 import Any

from base_reader import BaseReader

CASTS = {"float": float, "int": int, "string": str, "bool": bool}
DEFAULTS = {"float": 0.0, "int": 0, "string": "", "bool": False}


def resolve_proto(path):
    """'wib_pb2.GetSensors.Sensors' -> the GetSensors.Sensors class."""
    module_name, *attrs = path.split(".")
    obj = importlib.import_module(module_name)
    for attr in attrs:
        obj = getattr(obj, attr)
    return obj


def parse_fields(fields):
    """Normalize a YAML `fields` block to {name: {"size": n, "type": t}}.

    Accepts the short form `name: 4` (4 floats) or the long form
    `name: {size: 1, type: int}`.
    """
    parsed = {}
    for name, spec in (fields or {}).items():
        if isinstance(spec, dict):
            size = spec.get("size", 1)
            ftype = spec.get("type", "float")
        else:
            size, ftype = spec, "float"
        if ftype not in CASTS:
            raise ValueError(f"field '{name}': unknown type '{ftype}' (use {list(CASTS)})")
        parsed[name] = {"size": int(size), "type": ftype}
    return parsed


def load_device_type(type_cfg):
    """Turn one device-type block of zmq_metrics.yaml into ready-to-use specs."""
    envelope = resolve_proto(type_cfg["envelope"]) if type_cfg.get("envelope") else None
    messages = {}
    for group, spec in type_cfg["messages"].items():
        messages[group] = {
            "request": resolve_proto(spec["request"]),
            "request_args": spec.get("request_args") or {},
            "response": resolve_proto(spec["response"]),
            "any_response": spec.get("any_response", True),
            "fields": parse_fields(spec.get("fields")),
        }
    return envelope, messages


class ZMQReader(BaseReader):
    protocol = "ZMQ"

    def __init__(self, dev, host, port, envelope, messages, timeout_ms=2000, tpc=None):
        """
        envelope: protobuf class with an Any field `cmd` that wraps each request
                  (e.g. wib_pb2.Command), or None to send requests unwrapped.
        messages: output of load_device_type()[1].
        """
        self.dev = dev
        self.tpc = tpc
        self.host = host
        self.port = port
        self.envelope = envelope
        self.messages = messages
        self.timeout_ms = timeout_ms
        self._context = zmq.Context()

    def read(self):
        values = {}
        for group, spec in self.messages.items():
            req = spec["request"](**spec["request_args"])
            try:
                resp = self._request(req, spec["response"], spec["any_response"])
            except zmq.error.Again:
                # Device is not answering: don't wait a timeout for every group.
                print(f" [!] {self.dev}: '{group}' timed out on {self.host}:{self.port}, skipping this poll")
                break
            except Exception as e:
                print(f" [!] {self.dev}: error reading '{group}' on {self.host}:{self.port}: {e}")
                continue

            for name, fspec in spec["fields"].items():
                if not hasattr(resp, name):
                    continue
                cast = CASTS[fspec["type"]]
                value = getattr(resp, name)
                if isinstance(value, (int, float, str, bytes, bool)):
                    values[name] = cast(value)
                else:  # repeated field
                    values[name] = [cast(v) for v in value]
        return values

    def _request(self, req_msg, resp_cls, any_response):
        """One REQ/REP round trip. A fresh socket per call keeps a dead
        backend from leaving the REQ socket stuck in the wrong state."""
        sock = self._context.socket(zmq.REQ)
        try:
            sock.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
            sock.connect(f"tcp://{self.host}:{self.port}")

            if self.envelope is not None:
                wrapped = self.envelope()
                wrapped.cmd.Pack(req_msg)
                payload = wrapped.SerializeToString()
            else:
                payload = req_msg.SerializeToString()
            sock.send(payload, flags=zmq.DONTWAIT)

            resp_bytes = sock.recv()
            resp = resp_cls()
            if any_response:
                resp_any = Any()
                resp_any.ParseFromString(resp_bytes)
                if not resp_any.Unpack(resp):
                    raise TypeError(f"reply is '{resp_any.type_url}', expected "
                                    f"'{resp.DESCRIPTOR.full_name}' (check response/any_response "
                                    f"in zmq_metrics.yaml)")
            else:
                resp.ParseFromString(resp_bytes)
            return resp
        finally:
            sock.close(linger=0)

    def close(self):
        self._context.term()
