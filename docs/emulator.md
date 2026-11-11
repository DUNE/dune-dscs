# Device emulators

Run one device per process using the repository's existing environment:

```bash
uv sync
uv run python -m dune_dscs.emulator pdu
uv run python -m dune_dscs.emulator daphne
uv run python -m dune_dscs.emulator wib
```

Run each command in its own terminal. All bind to `127.0.0.1` by default.
Use `--host` and `--port` for other endpoints.

- PDU: SNMP v2c on UDP 1161, community `private`, ten outlets initially off.
  Use `--outlets N` to change the outlet count. Implements Raritan PDU2-MIB
  outlet names, count, GET/GETNEXT/GETBULK and SET on/off. For outlet 1,
  operation OID is `1.3.6.1.4.1.13742.6.4.1.2.1.2.1.1` (off=0, on=1);
  state OID is `1.3.6.1.4.1.13742.6.4.1.2.1.3.1.1` (on=7, off=8).
  Metering, sensors, power-cycle and SNMPv3 are not implemented.
- DAPHNE: ZMQ ROUTER with protobuf envelope v2 on TCP 40001.
- WIB: ZMQ REP with the bundled WIB protobuf definitions on TCP 1234.

Board configuration and monitoring use simulated state. State changes are
immediate; startup and hardware timing are not simulated. These are standalone
protocol emulators, without a fleet manager or an OPC UA server.

Protocol source revisions and hashes are in
`src/dune_dscs/emulator/protocols/protocol_sources.json`. PDU OIDs follow
Raritan PDU2-MIB revision 202305260000Z, DUNE DocDB 32655 v8.

## Connecting a bridge

The emulators use one asyncio event loop per process, with `zmq.asyncio` and
PySNMP's asyncio transport. A bridge can use these with `asyncua`. Keep blocking
device calls off the event loop; use a bounded thread pool and transport timeouts
when a library has no async interface.

For WIB requests, pack the command into `Command.cmd`, then send the serialized
`Command`. Parse the reply directly as the expected response type:

```python
command = wib_pb2.Command()
command.cmd.Pack(wib_pb2.GetSensors())
await socket.send(command.SerializeToString())
sensors = wib_pb2.GetSensors.Sensors()
sensors.ParseFromString(await socket.recv())
```

The bridge in `archive/bridge/ignition_pybridge.py` sends a bare `Any` and is
incompatible with this request format. DAPHNE replies use `correl_id` to identify
the request. Their `timestamp_ns` uses a monotonic clock, not a UTC sample time.

These endpoints are a starting point for bridge tests. Before deployment, check:

- Device values through the bridge and Ignition, including node IDs, types and units.
- Data quality and sample age when an emulator stops; healthy devices must keep updating.
- Recovery after restarting an emulator, and command readback after a timeout.
- Mixed monitoring and configuration load, with bounded concurrency and queue sizes.
- The target devices' authentication and the OPC UA certificate configuration.

Delayed replies, packet loss and frozen telemetry are not simulated. Current
results do not establish bridge capacity or hardware compatibility.
