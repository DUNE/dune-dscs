# Mainz Slow Controls Stress Tests

Stress tests for the Python ZeroMQ-to-OPC-UA bridge and the Ignition
Gateway using distributed device emulators.

Each emulator provides three values: one temperature and two voltages.
The tests increase the number of devices and record performance,
resource usage and communication reliability.

## Directory structure

## Directory structure

```text
stress_test/
├── bridge/
│   ├── ignition_pybridge.py
│   ├── ignition_pybridge_diagnostic.py
│   ├── zmq_devices_config.py
│   ├── zmq_sensor_config.py
│   ├── zmq_devices.yaml
│   └── zmq_sensors.yaml
├── emulators/
│   ├── zmq_emulator.py
│   ├── create_emulators.sh
│   └── stop_emulators.sh
├── diagnostics/
│   ├── ignition_tag_diagnostics.py          # Cached Gateway timer
│   ├── ignition_tag_diagnostics_uncached.py # Uncached Gateway timer
│   ├── monitor_emulators.py
│   ├── monitor_ignition.py
│   ├── run_bridge_test.sh
│   ├── run_bridge_test_emulator.sh
│   └── run_ignition_tests.sh
├── plotting/
│   ├── stress_test_result.py
│   ├── plot_ignition_results.py
│   ├── plot_bridge_ignition.py
│   └── plot_timer_comparison.py
├── results/           # Measurements grouped by test run
├── figures/           # Generated figures and summary tables
├── .runtime/          # One emulator process record file per host
├── zmq_em.proto
├── zmq_em_pb2.py
├── .gitignore
└── README.md
```

Results, figures and runtime files are local outputs excluded from Git.
The emulator launchers discard terminal output and do not create logs.

## Environment

The launchers use the existing Python environment:

```text
~/DSCS/opcua-env/bin/python
```

Activate it before running Python commands:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
```

The scripts use `pyzmq`, `protobuf`, `opcua`, `PyYAML` and `psutil`.
Plotting also requires `pandas`, `numpy` and `matplotlib`.

The Protobuf runtime must be compatible with the generated
`zmq_em_pb2.py` file. Regenerate that file when changing `zmq_em.proto`.

## Start and stop emulators

Run these commands on each emulator host:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
bash emulators/create_emulators.sh
```

The launcher starts 100 emulators on TCP ports 5555–5654.
Output is discarded, so no emulator log files are created.

One runtime file per host is stored at `.runtime/<hostname>.jsonl`.
It records the PID, process start time and port of each emulator.

Stop the recorded emulators on the same host:

```bash
bash emulators/stop_emulators.sh
```

The stop script verifies ownership, process start time and command
before sending SIGTERM. It waits up to ten seconds and retains records
for processes it could not stop.

Keep runtime records while the corresponding emulators are running.
The stop script manages instances started by this launcher.


## Bridge

The `bridge/` folder contains the ZeroMQ-to-OPC-UA bridge and its
configuration.

### Files

| File | Purpose |
|---|---|
| `ignition_pybridge.py` | Runs the bridge continuously using the device YAML configuration. |
| `ignition_pybridge_diagnostic.py` | Runs a fixed number of polling cycles and records stress-test measurements. |
| `zmq_devices_config.py` | Loads the device YAML configuration. |
| `zmq_sensor_config.py` | Loads the sensor-field configuration. |
| `zmq_devices.yaml` | Lists devices used by the continuous bridge. |
| `zmq_sensors.yaml` | Defines the sensor fields and number of values exposed per field. |

Both bridge versions use the shared `zmq_em_pb2.py` module at the
`stress_test` root.

### Preparation

Activate the Python environment and work from the `stress_test` root:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
```

Start the emulators on their configured hosts before running the bridge.
Run one bridge instance per host using TCP port 4840.

### Continuous bridge

Use this version to expose readings continuously without recording
stress-test metrics:

```bash
python bridge/ignition_pybridge.py
```

It reads devices from `bridge/zmq_devices.yaml`. For example:

```yaml
zmqdevice:
  - tpc: 3
    dev: 1
    host: "134.93.131.35"
    port: 5555
```

Each entry identifies a device, its host and its emulator port.

Sensor fields are loaded from `bridge/zmq_sensors.yaml`. The bridge
polls the devices sequentially, with a one-second delay before each
polling cycle and a two-second receive timeout per request.

Press Ctrl+C to stop the bridge.

### Diagnostic bridge

Run from the `stress_test` root:

```bash
python bridge/ignition_pybridge_diagnostic.py \
    --devices 10 \
    --cycles 300 \
    --warmup 30 \
    --output-dir results/timer_disabled
```

| Option | Meaning |
|---|---|
| `--devices` | Required number of emulators, from 1 to 1000. |
| `--cycles` | Measured polling cycles after warm-up. Default is 10. |
| `--warmup` | Warm-up duration in seconds. Default is 30. |
| `--output-dir` | CSV destination. Defaults to `stress_test/results`. Relative paths use the current working directory. |

The output directory is created automatically. This example saves
`results/timer_disabled/bridge_N10.csv`. Existing CSV files are never
overwritten.

The `timer_disabled` folder name labels the experiment. Disable the
Ignition diagnostic timer in Designer before running this case.

The shared `ignition_test_control.json` remains at the `stress_test` root.


### Diagnostic output

The diagnostic bridge creates `bridge_N<number>.csv` in the current
working directory and refuses to overwrite an existing file.

Each measured cycle records:

- UTC timestamp, cycle number, device count and variable count.
- Polling-cycle duration, including the one-second delay.
- Bridge process CPU usage and resident memory.
- Request attempts, successes, receive timeouts and errors.
- Failure percentage and successful acquisition rate.
- Mean, median, P95 and P99 latency for successful requests.
- ZeroMQ request and response payload throughput.
- OPC UA variable write count and write rate.
- Total response-parsing and node-update time.

Warm-up cycles update the nodes but are excluded from the CSV
measurements.

The bridge also updates `ignition_test_control.json` at the
`stress_test` root with the device count, run ID and active state.
The Ignition diagnostic timer uses this file to identify the test.

After a completed test, store its CSV with the corresponding run under
`results/`.

### OPC UA connection

Both versions expose the same endpoint:

```text
opc.tcp://<bridge-host>:4840/freeopcua/server/
```

Use `127.0.0.1` for `<bridge-host>` when Ignition runs on the same
computer. Otherwise, use the bridge computer's IP address.

The configured connection uses anonymous authentication with security
policy and mode set to None.

Sensor node identifiers retain this format:

```text
TPC<tpc>/WIB<device>/<field>/<index>
```

For example:

```text
TPC3/WIB1/Temp1/0
```

### Automated tests

Run the configured bridge-only sequence:

```bash
bash diagnostics/run_bridge_test.sh
```

Run the sequence with Ignition resource monitoring on the Gateway host:

```bash
bash diagnostics/run_ignition_tests.sh
```

Check device counts, cycle counts and warm-up settings in the selected
runner before starting.








## Bridge stress test

Run commands from the `stress_test` root with the Python environment
activated.

Run one device-count configuration:

```bash
python bridge/ignition_pybridge_diagnostic.py --devices 10 --cycles 300
```

Run the configured bridge test sequence:

```bash
bash diagnostics/run_bridge_test.sh
```

Check the device counts and cycle count in the runner before starting.
Bridge YAML configuration files are stored under `bridge/`.

The bridge records:

- Polling-cycle duration.
- Process CPU usage and resident memory.
- Request attempts, successes, timeouts and errors.
- Successful acquisition rate.
- Request latency statistics.
- ZeroMQ payload throughput in both directions.
- OPC UA variable write count and rate.
- Response parsing and node-update time.

## Ignition Gateway diagnostic scripts

The `diagnostics/` folder contains two Gateway timer scripts:

| File | Behaviour |
|---|---|
| `ignition_tag_diagnostics.py` | Caches validated tag paths once per run and reuses them. |
| `ignition_tag_diagnostics_uncached.py` | Rebuilds tag lists and browses paths on every timer execution. |

Both scripts measure tag completeness, tag quality, OPC UA connection
state and diagnostic collection time. They also record elapsed time and
timer-thread CPU time for each diagnostic operation.

### Install in Ignition Designer

1. Open the stress-test project in Ignition Designer.
2. In the Project Browser, expand **Scripting → Gateway Events → Timer**.
3. Right-click **Timer**, create a new timer script and name it
   `BridgeStressMonitor`.
4. Set the timer properties:

   | Property | Setting |
   |---|---|
   | Delay | `5000` ms |
   | Delay Type | `Fixed Delay` |
   | Threading | `Dedicated` |
   | Enabled | Checked |

5. Open the timer editor and replace its contents with the complete
   `handleTimerEvent()` function from the selected file. Keep one
   function definition.
6. Save the project to apply the Gateway script.

Enable only one diagnostic timer version at a time. Both versions
manage the same test tags and write to the same CSV files.

Fixed Delay waits five seconds after an execution finishes before
starting the next one.

### Configuration

Check these settings inside the selected script:

```python
BASE_DIR = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
OPC_SERVER = "bridge leonor 09"
```

`BASE_DIR` must be accessible to the Ignition Gateway process.
`OPC_SERVER` must match the OPC UA connection name configured in
Ignition.

The host ordering in the timer script must match `EMULATOR_HOSTS`
in `bridge/ignition_pybridge_diagnostic.py`.

### Running a test

Start the emulators and confirm the Ignition trial or licence is active.
Then run the diagnostic bridge or the Ignition test runner.

The timer reads `ignition_test_control.json` at the `stress_test` root.
It collects measurements while the control file marks a run as active.

For tests without diagnostic monitoring, uncheck **Enabled** on the
timer and save the project before starting.

### Output files

Both versions append measurements to:

```text
results/ignition_tag_diagnostics.csv
results/ignition_timer_profile.csv
```

The results directory is created automatically. These destinations are
configured inside the Gateway script; the bridge's `--output-dir`
option controls only the bridge CSV.

The cached version checks tag paths at setup and again at the end of
the run. Its CSV completeness counts come from the setup check.
Tag quality and connection state are sampled on every active execution.

### Process resource monitoring

Gateway CPU usage and RAM are measured separately by
`diagnostics/monitor_ignition.py`, started by the Ignition test runner.
The Gateway timer's CPU timings describe its own thread and individual
diagnostic operations.

## Ignition stress test

Before starting:

1. Confirm the emulators are running on the configured hosts.
2. Confirm the Ignition Gateway is running and its trial or licence is active.
3. Confirm the OPC UA connection points to the bridge host.
4. Set the diagnostic timer to the intended enabled or disabled state.
5. Check device counts, warm-up and measured cycles in the runner.

Run on the host containing the Ignition Gateway:

```bash
cd ~/dune-dscs/stress_test
bash diagnostics/run_ignition_tests.sh
```

`diagnostics/monitor_ignition.py` measures the local Gateway Java
process's CPU usage and resident memory. The bridge diagnostic code
measures the bridge's own resources.

When enabled, the Ignition Gateway timer script records tag
completeness, tag quality, OPC UA connection state and diagnostic
collection time. It reads `ignition_test_control.json` at the
`stress_test` root to identify the active run.

The runner supports resuming tests. Its completion check uses the
corresponding bridge CSV, so an existing completed CSV can cause a
device count to be skipped.

## Results and plots

Keep each completed test run in its own folder under `results/`.
Distinguish between:

- Timer-enabled and timer-disabled runs.
- Original and cached diagnostic scripts.
- Complete runs and partial repeats.

The current runners write measurement files at the `stress_test` root.
Move completed measurements into their run folder before starting a
separate experiment.

Generate plots from the `stress_test` root:

```bash
python plotting/stress_test_result.py
python plotting/plot_ignition_results.py
python plotting/plot_bridge_ignition.py
python plotting/plot_timer_comparison.py
```

The plotting scripts read archived measurements under `results/` and
save figures and summary tables under `figures/`.

Check the dataset paths in each plotting script before running it.
Existing figures with the same output names are overwritten.

## Ignition Gateway script path

The diagnostic timer script is stored in Ignition Designer and must
use the same base directory as the bridge:

```python
BASE = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
```

Replace any remaining references to `Tutorials/workshop2026` in that
Gateway script.

## Interpreting measurements

- Process CPU usage of 100% corresponds to one logical CPU.
- RAM measurements are process resident memory.
- P5–P95 bands describe variability across samples.
- ZeroMQ payload throughput excludes network protocol overhead.
- Good tag quality alone does not establish data freshness.
- Diagnostic monitoring adds overhead to the Gateway.