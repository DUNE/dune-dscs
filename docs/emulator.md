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

Board configuration and monitoring use simulated state. `--time-scale 1`
applies configured waits; the default skips waits. These are standalone
protocol emulators, without a fleet manager or an OPC UA server.

Protocol source revisions and hashes are in
`src/dune_dscs/emulator/protocols/protocol_sources.json`. PDU OIDs follow
Raritan PDU2-MIB revision 202305260000Z, DUNE DocDB 32655 v8.
