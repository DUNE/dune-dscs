# A5202 through the shared OPC UA bridge

`dune_dscs.devices.fers.A5202` connects to an A5202 or DT5202 through CAEN
FERSlib. Direct Ethernet is the intended first connection. Direct USB paths
are also accepted. TDlink and concentrator setup are not implemented.

`archive/bridge/ignition_pybridge.py` uses this client to publish board identity,
firmware revisions, temperature, bias voltage, measured voltage and current,
current limit, and high voltage (HV) status. A5202 objects share the existing
OPC UA server, namespace and polling loop with the other devices. Their OPC UA
variables are read-only. The underlying Python client also provides explicit
HV setters and 32-bit register access for separate control programs.

**Opening a connection stops acquisition.** In FERSlib 2.2.2,
`FERS_OpenDevice` sends an acquisition stop command and can write calibration
settings. Use this client when it owns the board. For monitoring during DAQ,
the process that already owns the FERSlib connection needs to expose the
readings; opening another connection is not a passive monitoring operation.

## Install FERSlib

Install CAEN FERSlib 2.2.2 from the [CAEN product page](https://caen.it/products/caen-ferslib-library/)
or [CAEN's source repository](https://github.com/caenspa/caen-ferslib).
The Python binding accepts 2.2.x releases; its declarations were checked against
2.2.2. Other release families are rejected before a board is opened.
FERSlib is a separate native dependency; `uv sync` does not install it.

On Linux, CAEN's source build requires a C/C++ compiler with C++17 support,
make, pkg-config and the libusb 1.0 development package. For a local installation:

```bash
git clone https://github.com/caenspa/caen-ferslib.git
cd caen-ferslib
git checkout 6a77b986b08c8ccde1c80b3ad498aeddb93045d1
./configure --prefix="$HOME/.local"
make
make install
```

Set the shared library path in the shell where you run dune-dscs:

```bash
export CAEN_FERSLIB_LIBRARY="$HOME/.local/lib/libcaenferslib.so"
```

You can also pass `library="/path/to/libcaenferslib.so"` to `A5202`.
Without either setting, the client uses the system library search path.
This binding uses Python's standard library and adds no Python dependencies.
USB access also needs the permissions and drivers described by CAEN.

## Add the board to the bridge

Add a `fers_devices` entry to `archive/bridge/devices.yaml`. Replace the example
address with the board's IPv4 address:

```yaml
fers_devices:
  - id: a5202_1
    path: eth:192.0.2.1
    poll_interval: 5
    detector_temperature: false
```

The checked-in configuration uses `fers_devices: []`, so it opens no FERS board
by default. Set `detector_temperature: true` only when an external sensor is
fitted and configured. `library: /path/to/libcaenferslib.so` can override the
environment setting for a device.

From the repository root, install the Python environment and start the same
bridge used by the existing devices:

```bash
uv sync
cd archive/bridge
uv run python ignition_pybridge.py
```

The endpoint remains `opc.tcp://<bridge-host>:4840/freeopcua/server/` with the
`OPCUASERVER` namespace. In Ignition, browse `Objects / a5202_1`. The string
node IDs use `a5202_1/<field>`, including `voltage_v`, `current_ma`,
`board_temperature_c`, `pid`, `model_name`, `fpga_firmware`, `mcu_firmware`,
`library_version`, `hv_enabled`, `hv_ramping`, `hv_overcurrent`, and
`hv_overvoltage`. Numbers, booleans and strings retain their OPC UA types.

The bridge also publishes `read_ok`, `last_error`, and `last_success_unix_s`.
Telemetry starts with `BadWaitingForInitialData` quality. If a poll fails,
its readings have `BadNoCommunication` quality and retain their last values;
the last-success time is unchanged. Other devices continue to be polled.
A later successful poll restores good quality. A missing native library
appears in `last_error` and does not stop the other device readers.

One connection stays open between polls. A read failure does not automatically
close and reopen the board. If the native connection cannot recover, restart
the bridge once the board is available. Closing the bridge releases the
connection and leaves the HV output at its current setting.

## Read directly from Python

For a separate diagnostic session, replace `192.0.2.1` with the board's IPv4 address:

```bash
uv sync
uv run python examples/fers_monitor.py eth:192.0.2.1
```

This example prints one set of readings as JSON. It opens and closes the
connection once. It does not set bias voltage, change the current limit, or
switch the HV output. The connection side effects described above still apply.

Use the client in a Python program:

```python
from dune_dscs.devices.fers import A5202

with A5202("eth:192.0.2.1") as board:
    print(board.board_info())
    print(board.read("voltage_v"))
    print(board.read("current_ma"))
    print(board.hv_status())
```

USB paths use `usb:0` for an enumeration index or `usb:12345` for a board PID.
Keep the connection open between polls. Each call blocks until FERSlib returns;
the wrapper does not add timeouts or retries. Calls from this wrapper share a
process-wide lock because FERSlib stores board state and error text globally.
This lock does not coordinate with other processes or other FERSlib bindings.

| Quantity passed to `read()` | Meaning | Unit |
| --- | --- | --- |
| `board_temperature_c` | Board sensor between the MCU and FPGA | °C |
| `fpga_temperature_c` | FPGA die temperature | °C |
| `hv_temperature_c` | HV module temperature | °C |
| `detector_temperature_c` | External detector sensor, if fitted and configured | °C |
| `bias_voltage_v` | Bias setpoint read from the HV register | V |
| `voltage_v` | Measured HV output voltage | V |
| `current_limit_ma` | Current limit read from the HV register | mA |
| `current_ma` | Measured output current | mA |

`hv_status()` returns `enabled`, `ramping`, `overcurrent`, and `overvoltage`.
The readings are separate hardware calls, not an atomic snapshot.
`board_info()` returns the identity cached by FERSlib when the board opened.
SDK errors raise `FersError` with the operation, numeric code, and error text.
Invalid temperatures reported as CAEN's `999` sentinel and non-finite readings
also raise `FersError`, with `code=None`.

## Write settings

`set_bias_voltage(volts)`, `set_current_limit(milliamps)`, and
`set_hv_enabled(True/False)` write to the hardware immediately.
The wrapper checks the A5202's [published limits](https://caen.it/products/a5202/):
20–85 V and a maximum current of 10 mA. Choose settings within the connected
detector's limits. Closing the client leaves the HV output as it is.

`read_register(address)` and `write_register(address, value)` accept unsigned
32-bit integers. Use the register map for the board's firmware. Raw writes
bypass the checks made by the HV setters.

`FERS_GetParam` is deliberately not used for monitoring: it reads FERSlib's
in-memory configuration. `FERS_SetParam` also only changes that configuration
until `FERS_configure` applies it. The HV methods above use the hardware APIs.
FERSlib may initialize its HV interface on the first HV register access.

## Verification

Run the tests and repository lint check:

```bash
uv run pytest tests/test_fers.py
uv run ruff check
```

The tests compile a small C test double and exercise the actual ctypes boundary,
including structure alignment, 32-bit values, float values, HV flags, failure
handling, connection cleanup, and input limits. The bridge tests also use a live
local OPC UA client to check typed readings, rejected client writes, failure
quality, recovery, and a shared endpoint with another device. They require `cc` and skip if
it is absent. To check the test double's declarations against CAEN's header:

```bash
FERSLIB_INCLUDE_DIR=/path/to/caen-ferslib/include uv run pytest tests/test_fers.py tests/test_fers_bridge.py
```

The reference is CAEN FERSlib 2.2.2, commit
`6a77b986b08c8ccde1c80b3ad498aeddb93045d1`, particularly
[`include/FERSlib.h`](https://github.com/caenspa/caen-ferslib/blob/6a77b986b08c8ccde1c80b3ad498aeddb93045d1/include/FERSlib.h),
[`src/FERSlib.c`](https://github.com/caenspa/caen-ferslib/blob/6a77b986b08c8ccde1c80b3ad498aeddb93045d1/src/FERSlib.c),
and the supplied Demo5202 program. The vendor library is not bundled.

No physical A5202 has been tested with this client. Hardware qualification
still needs the board address, installed FERSlib and firmware versions, and
comparison of the readings and permitted writes with CAEN's tools on that board.
