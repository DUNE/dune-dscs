# OPC UA bridge

One asyncio process reads WIB, DAPHNE and Raritan PDU endpoints and publishes
their values through `asyncua`. Use one technology or a mixed fleet.

Start the [three emulators](emulator.md) in separate terminals, then run:

```bash
uv run python -m dune_dscs.bridge examples/bridge.yaml
```

Select one technology with `--kind wib`. Repeat `--kind` to select several.
Use `--endpoint opc.tcp://127.0.0.1:4842/dune/` when running another instance.
Each instance owns its configured device connections and polling tasks.

Use the [measurement tools](measurements.md) for native query latency, timeouts,
process resources and OPC UA read measurements.

## Configuration

The [example](../examples/bridge.yaml) selects device addresses and measurements.
Each device needs an `id`, `kind`, `endpoint` and `variables` mapping.
Its optional `period` is the polling interval in seconds (default 1).
`timeout` limits each device read; `concurrency` bounds simultaneous reads.
One task per device prevents overlapping polls or a growing request queue.

Each variable has a `source`, OPC UA `type`, optional `unit` and optional
`values` mapping. The mapping translates native codes, such as PDU on/off
values 7 and 8, into the common value type. Types are Boolean, Int32, UInt32,
Int64, UInt64, Double and String. Sources are scalar fields; use numeric
indices to select array entries.

| Device | Sources |
|---|---|
| WIB | `sensors.<field>`, `femb.<field>`, `timing.<field>`, `version.<field>` |
| DAPHNE | `info.<field>`, `counters.<field>`, `test_register.<field>` |
| PDU | Numeric SNMP OID |

WIB and DAPHNE field names follow the bundled protobuf definitions. A read
fetches each requested message group once. DAPHNE `info` readings from the
current emulator are placeholders; the example uses threshold readback instead.
For changing synthetic sensors and channel-0 counters, start the emulators
with `--vary` and use `examples/bridge-varying.yaml`. See the
[telemetry scope and hardware limits](emulator.md).

## Common OPC UA view

Default namespace: `urn:dune:dscs:bridge`. Every device appears under `Devices`.
Node IDs use `Devices.<device-id>.<variable-name>`; for example,
`nsu=urn:dune:dscs:bridge;s=Devices.wib-001.TemperatureC`.
Each measurement has a string `Unit` property.

Every device also exposes:

| Field | Meaning |
|---|---|
| Technology, Endpoint | Native device interface |
| Available | The last complete read succeeded |
| Sequence | Number of successful acquisitions |
| LastSuccess | UTC time when the last complete read finished |
| LastError | Most recent read or conversion error |

Measurements start with `BadWaitingForInitialData`. Successful reads publish
Good values with a UTC source timestamp. Communication failures publish
`BadNoCommunication`; invalid replies or conversions publish `BadDecodingError`.
A failed read keeps the last successful source timestamp. All measurements
for that device share the outcome of its complete read. Healthy devices
continue independently; failed devices retry on later polls.

## Ignition

Add an OPC UA connection to the configured endpoint, then browse `Devices`
and create subscribed OPC tags. Use Sequence or LastSuccess to check freshness:
an unchanged measurement can retain its previous Ignition tag timestamp.
Ignition may display `BadNoCommunication` as `Bad_NotConnected`.

This first pass is read-only. Native device clients perform configuration;
the bridge publishes their readback. It currently implements WIB, DAPHNE and
SNMP v2c PDU readers. IPMI/uTCA, PTC and other technologies need their own
reader adapters. Each adapter returns the same source-to-value mapping.

The default endpoint is loopback, with anonymous OPC UA and no message
encryption. Use an SSH tunnel for the remote test. OPC UA certificates,
authentication, hardware behavior and production capacity are not qualified.

Run all checks locally:

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check src tests --extend-exclude '*_pb2.py'
```
