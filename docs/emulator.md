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
immediate unless an optional response wait is selected below. Startup, sensor
acquisition and calibration timing are not simulated. These are standalone
protocol emulators, without a fleet manager or an OPC UA server.

Use a response timing profile to repeat measured waits without blocking other devices:

```sh
python -m dune_dscs.emulator pdu --timing examples/timing/pdu-measured.json
python -m dune_dscs.emulator daphne --timing examples/timing/daphne15-measured.json
python -m dune_dscs.emulator wib --timing examples/timing/wib-source-estimate.json
```

The PDU samples were measured from `dune-fd-test01` to the Ethernet-connected
PX4-54A7CR-A0, serial R1460000103. SNMP GET waits are grouped by variable count.
The DAPHNE samples came from `np04-onl-004` to `np04-daphne-015` at CERN.
These are short traces: ten samples per PDU request shape and five per DAPHNE
operation. They do not establish tail latency under production load.

The WIB profile is a **source estimate**, not a measurement. At firmware source
revision `ee0a4cd528f6e9a2fef90c205088173b149a91f2`, `GetSensors` contains
2.466 seconds of fixed waits. I2C, OS, queue and network time are additional.
The board version and deployed firmware still need checking. The bridge's
default two-second timeout is too short for this profile; use a longer timeout
and a polling period suitable for the fleet's concurrency limit.

`delays_ms` maps native operation names to lists of waits in milliseconds.
Samples repeat in order; operations absent from the file remain immediate.
Measured round trips are used as added waits, so local emulator and transport
overhead is additional. DAPHNE general information can contain cached sensor
values: matching its reply time does not model the age of those measurements.
SNMP delays hold at most 64 pending datagrams per emulator; excess UDP requests
are dropped. This is a test limit, not a measured PDU queue size.

Protocol source revisions and hashes are in
`src/dune_dscs/emulator/protocols/protocol_sources.json`. PDU OIDs follow
Raritan PDU2-MIB revision 202305260000Z, DUNE DocDB 32655 v8.

Run the unit tests with `uv run python -m unittest discover -s tests -v`.
They check reply formats, state readback and rejected requests for each emulator.

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

Response waits are optional. Packet loss, frozen telemetry and the full hardware
acquisition cycle are not simulated. Current
results do not establish bridge capacity or hardware compatibility.
