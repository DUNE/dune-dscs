"""Read FERS telemetry through the same OPC UA bridge as other devices."""

import socket

import pytest
from opcua import Client


def make_poller(bridge, server, idx, library):
    return bridge.initialize_fers_pollers(
        server.get_objects_node(), idx,
        [{"id": "a5202_1", "path": "eth:192.0.2.1", "library": library}],
    )[0]


def raw_value(node, ua):
    # A normal read raises on bad quality; read the full DataValue instead.
    return node.get_attributes([ua.AttributeIds.Value])[0]


def test_fers_uses_existing_server_with_typed_read_only_nodes(bridge, sdk):
    library, control = sdk
    server = bridge.Server()
    idx = server.register_namespace("urn:dune:test")
    poller = make_poller(bridge, server, idx, library)
    reader, nodes = poller["reader"], poller["nodes"]
    ua = bridge.ua
    assert control.stub_opened() == 0
    assert raw_value(nodes["voltage_v"], ua).StatusCode.value == ua.StatusCodes.BadWaitingForInitialData
    assert nodes["voltage_v"].get_data_type_as_variant_type() == ua.VariantType.Double
    assert nodes["hv_enabled"].get_data_type_as_variant_type() == ua.VariantType.Boolean
    assert nodes["model_name"].get_data_type_as_variant_type() == ua.VariantType.String
    assert nodes["pid"].get_data_type_as_variant_type() == ua.VariantType.Int64
    assert "detector_temperature_c" not in nodes

    # Existing sensor objects share the same address space and endpoint.
    instrument = server.get_objects_node().add_object(idx, "instrument1")
    other_nodes = bridge.initialize_simple_nodes(instrument, idx, "instrument1", ["temperature"])
    bridge.update_simple_nodes(other_nodes, {"temperature": 12.5})

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    endpoint = f"opc.tcp://127.0.0.1:{port}/test"
    server.set_endpoint(endpoint)
    server.start()
    try:
        bridge.poll_fers(reader, nodes)
        assert control.stub_writes() == 0
        assert control.stub_opened() == 1
        with Client(endpoint) as client:
            voltage = client.get_node(ua.NodeId("a5202_1/voltage_v", idx))
            assert voltage.get_value() == pytest.approx(54.9)
            assert client.get_node(nodes["pid"].nodeid).get_value() == 12345
            assert client.get_node(nodes["hv_enabled"].nodeid).get_value() is False
            assert client.get_node(other_nodes["temperature"].nodeid).get_value() == 12.5
            for node in nodes.values():
                assert ua.AccessLevel.CurrentWrite not in node.get_access_level()
            with pytest.raises(ua.UaStatusCodeError) as error:
                voltage.set_value(60.0)
            assert error.value.code == ua.StatusCodes.BadUserAccessDenied

            last_success = nodes["last_success_unix_s"].get_value()
            control.stub_fail(-2)
            bridge.poll_fers(reader, nodes)
            assert nodes["read_ok"].get_value() is False
            assert "simulated communication failure" in nodes["last_error"].get_value()
            assert nodes["last_success_unix_s"].get_value() == last_success
            failed = raw_value(voltage, ua)
            assert failed.StatusCode.value == ua.StatusCodes.BadNoCommunication
            assert failed.Value.Value == pytest.approx(54.9)
            assert client.get_node(other_nodes["temperature"].nodeid).get_value() == 12.5

            bridge.poll_fers(reader, nodes)
            assert nodes["read_ok"].get_value() is True
            assert raw_value(voltage, ua).StatusCode.is_good()
            assert control.stub_opened() == 1
            assert control.stub_writes() == 0
    finally:
        reader.close()
        server.stop()
    assert control.stub_opened() == 0


def test_missing_native_library_does_not_break_other_bridge_readings(bridge):
    server = bridge.Server()
    idx = server.register_namespace("urn:dune:test")
    poller = make_poller(bridge, server, idx, "/does/not/exist")
    bridge.poll_fers(poller["reader"], poller["nodes"])
    bridge.poll_fers(poller["reader"], poller["nodes"])
    nodes = poller["nodes"]
    assert nodes["read_ok"].get_value() is False
    assert nodes["last_error"].get_value()
    assert raw_value(nodes["voltage_v"], bridge.ua).StatusCode.value == bridge.ua.StatusCodes.BadNoCommunication
    poller["reader"].close()


def test_config_loads_fers_without_changing_other_device_lists(bridge, tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text("fers_devices:\n  - id: a5202_1\n    path: eth:192.0.2.1\n")
    devices = bridge.DevicesConfig(config)
    assert devices.get_fers_devices() == [{"id": "a5202_1", "path": "eth:192.0.2.1"}]
    assert devices.get_ipmi_devices() == []
    assert devices.get_snmp_devices() == []
    assert devices.get_scpi_devices() == []


def test_external_temperature_is_optional(bridge, sdk):
    library, _ = sdk
    server = bridge.Server()
    idx = server.register_namespace("urn:dune:test")
    poller = bridge.initialize_fers_pollers(
        server.get_objects_node(), idx,
        [{"id": "a5202_1", "path": "eth:192.0.2.1", "library": library,
          "detector_temperature": True}],
    )[0]
    try:
        bridge.poll_fers(poller["reader"], poller["nodes"])
        assert poller["nodes"]["detector_temperature_c"].get_value() == 21.75
    finally:
        poller["reader"].close()
