#!/usr/bin/env python3
"""Expose configured ZeroMQ emulator readings through an OPC UA server."""

import sys
import time
from pathlib import Path

import zmq
from google.protobuf.any_pb2 import Any
from opcua import Server, ua

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "opc.tcp://0.0.0.0:4840/freeopcua/server/"
REQUEST_TIMEOUT_MS = 2000
CYCLE_DELAY_S = 1

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


def initialize_nodes(parent, namespace, nodes, mapping, tpc, device):
    """Create sensor objects and writable variables with stable node IDs."""
    for name, count in mapping.items():
        sensor_object = parent.add_object(namespace, name)
        nodes[name] = []
        initial_value = 0 if name == "addr" else 0.0

        for index in range(count):
            node_id = ua.NodeId(
                f"TPC{tpc}/WIB{device}/{name}/{index}", namespace
            )
            variable = sensor_object.add_variable(
                node_id, f"{name}_{index}", initial_value
            )
            variable.set_writable()
            nodes[name].append(variable)


def update_node(response, nodes):
    """Copy available response fields into one device's OPC UA nodes."""
    for name, variables in nodes.items():
        if not hasattr(response, name):
            continue

        value = getattr(response, name)

        if hasattr(value, "__len__") and not isinstance(value, (str, bytes)):
            for variable, item in zip(variables, value):
                variable.set_value(item)
        elif variables:
            variables[0].set_value(value)


def zmqd_request(
    context, host, port, request, response_class, label,
    use_any_response=True,
):
    """Use a fresh request socket and return a response or None on error."""
    request_socket = context.socket(zmq.REQ)
    machine = WEBER_NAMES.get(host, host)

    try:
        request_socket.connect(f"tcp://{host}:{port}")
        request_socket.setsockopt(zmq.RCVTIMEO, REQUEST_TIMEOUT_MS)

        envelope = Any()
        envelope.Pack(request)
        request_socket.send(
            envelope.SerializeToString(), flags=zmq.DONTWAIT
        )
        response_bytes = request_socket.recv()
        response = response_class()

        if use_any_response:
            envelope = Any()
            envelope.ParseFromString(response_bytes)
            envelope.Unpack(response)
        else:
            response.ParseFromString(response_bytes)

        return response

    except zmq.error.Again:
        print(f"[!] Timeout: {label} on {machine}, port {port}")