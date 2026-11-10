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
│   ├── monitor_emulators.py
│   ├── monitor_ignition.py
│   ├── run_bridge_test.sh
│   ├── run_bridge_emulator_tests.sh # Tests both bridge measurements and emulators CPU usage
│   └── run_ignition_tests.sh
├── ignition_monitoring_scripts/
│   ├── ignition_monitoring_scripts/ignition_tag_diagnostics_configurable.py        # Both Cached and Uncached Gateway timer
│   ├── ignition_tag_diagnostics.py          # Cached Gateway timer
│   ├── ignition_tag_diagnostics_uncached.py # Uncached Gateway timer
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


## Bridge-only test runner

`diagnostics/run_bridge_test.sh` runs the diagnostic bridge for the
selected device counts. It records bridge measurements without starting
Ignition or emulator resource monitors.

### Configuration

Edit `DEVICE_COUNTS` near the top of the script:

```bash
DEVICE_COUNTS=(10 110 210 310 410 510 610 710 810 900)
```

The default list currently contains only `110`.

Other defaults are:

| Setting | Default |
|---|---|
| `CYCLES` | `300` measured cycles |
| `WARMUP` | `30` seconds |
| `RESULTS_DIR` | `results/bridge_only/` |

### Run

Start the required emulators, then run:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test

bash diagnostics/run_bridge_test.sh
```

For a custom experiment folder:

```bash
RESULTS_DIR=results/bridge_only_repeat \
bash diagnostics/run_bridge_test.sh
```

Override cycles and warm-up when needed:

```bash
CYCLES=10 WARMUP=5 \
RESULTS_DIR=results/bridge_validation \
bash diagnostics/run_bridge_test.sh
```

### Output

Each device count produces:

```text
results/bridge_only/bridge_N<number>.csv
```

The directory is created automatically. The runner refuses to overwrite
existing bridge CSVs and does not resume partial runs.

For a test without Gateway diagnostic activity, disable the Ignition
diagnostic timer in Designer before starting.

## Bridge and emulator resource test runner

`diagnostics/run_bridge_emulator_tests.sh` runs the diagnostic bridge
while measuring emulator CPU usage and resident memory on each
configured host.

It does not start the Ignition resource monitor.

### Preparation

Before running:

1. Start the emulators on every configured host.
2. Check that `HOSTS` matches the host list in the diagnostic bridge.
3. Confirm the shared repository and Python environment are accessible
   at the same paths on each host.
4. Confirm passwordless SSH works from the runner host to the remote
   emulator hosts.

For example:

```bash
ssh -o BatchMode=yes lgoncalve@134.93.131.35 hostname
```

The local host is monitored directly. Remote hosts are monitored through
SSH.

For a test without Gateway diagnostic activity, disable the Ignition
diagnostic timer in Designer.

### Configuration

Edit `DEVICE_COUNTS` and `HOSTS` near the top of the script.

Defaults are:

| Setting | Default |
|---|---|
| Device counts | `10 110 210 310 410 510 610 710 810 900` |
| `CYCLES` | `300` measured cycles |
| `WARMUP` | `30` seconds |
| `RESULTS_DIR` | `results/emulator_bridge/` |

### Run

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test

bash diagnostics/run_bridge_emulator_tests.sh
```

For a custom experiment folder:

```bash
RESULTS_DIR=results/emulator_bridge_repeat \
bash diagnostics/run_bridge_emulator_tests.sh
```

For a shorter validation run:

```bash
CYCLES=10 WARMUP=5 \
RESULTS_DIR=results/emulator_bridge_validation \
bash diagnostics/run_bridge_emulator_tests.sh
```

These overrides retain the device-count list configured in the script.

### Output and monitoring

For each device count, the selected results folder contains:

```text
bridge_N<number>.csv
emulators_N<number>_Weber02.csv
emulators_N<number>_Weber03.csv
...
```

Each emulator CSV records:

- UTC timestamp.
- Number of accessible monitored emulator processes.
- Sum of process CPU usage.
- Sum of process resident memory in MB.

The monitors track this user's emulator processes found at startup,
including idle emulators. Summed RSS can count shared memory pages
more than once.

The runner waits for a sample from every host before starting the
bridge. Emulator monitoring includes bridge startup and warm-up;
the bridge CSV contains measured cycles only.

At the end, a shared stop marker ends the monitors. This stops resource
monitoring, while the emulators continue running.

Errors appear in the terminal. No separate `.err` files are created.
Existing result files are protected from overwriting. For a fresh
experiment, choose a new `RESULTS_DIR`.

The runner verifies the expected bridge cycles before reporting
completion. It does not resume partial runs.
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


## Ignition stress test

`diagnostics/run_ignition_tests.sh` runs the bridge for several device
counts while measuring the Ignition Gateway's CPU usage and RAM.

Run it on the computer hosting the Ignition Gateway. In the Mainz
setup, this is Weber09.

### Gateway preparation

Install the function from:

```text
ignition_monitoring_scripts/ignition_tag_diagnostics_configurable.py
```

In Ignition Designer:

1. Open the stress-test project.
2. Expand **Scripting → Gateway Events → Timer**.
3. Create or open `BridgeStressMonitor`.
4. Replace its function with the complete `handleTimerEvent()` function
   from the configurable script.
5. Use these settings:

   | Property | Value |
   |---|---|
   | Delay | `5000` ms |
   | Delay Type | `Fixed Delay` |
   | Threading | `Dedicated` |
   | Enabled | Checked |

6. Save the project.

Use one diagnostic timer. The configurable script replaces the
separate cached and uncached versions for these tests.

Keep the Gateway timer enabled in Designer for every automated mode.
The runner controls whether it performs recurring diagnostic collection.

Before testing, confirm:

- The Ignition trial or licence is active.
- The OPC UA connection name matches `OPC_SERVER` in the Gateway script.
- The emulator hosts and ordering match the bridge configuration.
- Enough emulators are running for the selected device counts.

### Default settings

| Setting | Default |
|---|---|
| Device counts | `10 110 210 310 410 510 610 710 810 900` |
| Measured cycles per device count | `300` |
| Warm-up | `30` seconds |
| `TIMER_ENABLED` | `true` |
| `CACHE_ENABLED` | `true` |
| Results folder | `results/timer_cached/` |

Edit `DEVICE_COUNTS` near the top of `run_ignition_tests.sh` to change
the tested loads. The other settings below can be supplied as
environment variables.

### Run the default case

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test

bash diagnostics/run_ignition_tests.sh
```

This enables diagnostic collection with cached tag paths.

### Case 1 — Diagnostic collection disabled

```bash
TIMER_ENABLED=false \
bash diagnostics/run_ignition_tests.sh
```

Results are saved under:

```text
results/diagnostics_disabled/
```

Ignition configures the expected tags and checks their initial quality.
Once ready, the timer skips recurring diagnostic collection.

Caching is ignored in this mode.

The Gateway timer still reads the control file every five seconds.
This differs from unchecking **Enabled** in Designer, which stops the
timer entirely.

### Case 2 — Diagnostic collection enabled, without caching

```bash
TIMER_ENABLED=true CACHE_ENABLED=false \
bash diagnostics/run_ignition_tests.sh
```

Results are saved under:

```text
results/timer_uncached/
```

The Gateway rebuilds tag lists and browses tag paths on every diagnostic
execution. Tags are created only when a new run starts.

### Case 3 — Diagnostic collection enabled, with caching

```bash
TIMER_ENABLED=true CACHE_ENABLED=true \
bash diagnostics/run_ignition_tests.sh
```

Results are saved under:

```text
results/timer_cached/
```

The Gateway builds and validates tag paths once per run, then reuses
them for subsequent reads. It checks completeness again when the run
ends.

In this mode, CSV completeness counts come from the initial check.
Quality and connection state are sampled during recurring collection.

### Change cycles and warm-up

For example, run the cached case with ten measured cycles and
five seconds of warm-up:

```bash
TIMER_ENABLED=true CACHE_ENABLED=true \
CYCLES=10 WARMUP=5 \
RESULTS_DIR=results/cached_validation \
bash diagnostics/run_ignition_tests.sh
```

Warm-up is measured in seconds.

### Start an experiment in a custom folder

Set `RESULTS_DIR` to choose the output folder when starting any case:

```bash
TIMER_ENABLED=true CACHE_ENABLED=false \
RESULTS_DIR=results/my_experiment \
bash diagnostics/run_ignition_tests.sh
```

The folder is created automatically. Bridge measurements, Ignition
measurements and test settings are saved there.

Use a new folder name for each independent experiment.

### Repeat an experiment

Choose a new folder to retain the previous measurements:

```bash
TIMER_ENABLED=true CACHE_ENABLED=true \
RESULTS_DIR=results/timer_cached_repeat \
bash diagnostics/run_ignition_tests.sh
```

Relative results paths are resolved from the `stress_test` root.

The selected output directory is passed to the bridge and the Gateway
script automatically.

### What happens during each device-count test

1. The runner checks for completed or unfinished measurements.
2. The Python monitor starts measuring the local Ignition Java process.
3. The bridge starts and publishes the device count and test settings.
4. Ignition creates the expected tags.
5. The bridge waits for Good tag quality and a connected OPC UA state.
6. The bridge performs warm-up, followed by the measured polling cycles.
7. The runner stops the resource monitor and verifies the outputs.

Gateway setup has a default timeout of 60 seconds.

### Output files

Each experiment folder contains:

| File | Contents |
|---|---|
| `test_settings.json` | Device counts, cycles, warm-up and diagnostic mode. |
| `bridge_N<number>.csv` | Bridge measurements for one device count. |
| `ignition_resources.csv` | Gateway CPU and RAM samples across device counts. |
| `ignition_tag_diagnostics.csv` | Tag quality, completeness and connection samples when collection is enabled. |
| `ignition_timer_profile.csv` | Diagnostic operation timings when collection is enabled. |

The resource monitor includes setup, warm-up and measured cycles.
The bridge CSV includes only measured cycles.

The shared control file remains at the `stress_test` root. Gateway
readiness status and temporary monitor files are stored under
`.runtime/`.

### Resume an interrupted experiment

Run the same command with the same settings and results folder.

Completed device counts are skipped. For an unfinished device count,
the runner removes its previous samples and repeats that configuration.

A completed bridge CSV must have the expected cycles and associated
Ignition resource samples. Enabled collection also requires Gateway
diagnostic and profiling samples.

If the folder's saved settings differ, the runner stops. Choose a new
`RESULTS_DIR` for a different experiment.


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

## Plot bridge results

Run commands from the `stress_test/` directory with the Python
environment activated.

`plotting/plot_bridge_results.py` combines bridge performance plots
and peak analysis. It reads files named `bridge_N<number>.csv` from
one selected experiment folder.

### Bridge-only results

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/bridge_only
```

### Bridge and Ignition resource comparison

Provide the folder containing `ignition_resources.csv`:

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/timer_disabled_complete \
    --ignition-dir results/timer_disabled_complete
```

The Ignition comparison includes CPU usage and resident memory.
It uses all resource samples in the selected file, which may include
warm-up.

### Choose an output folder

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/my_experiment \
    --output-dir figures/my_experiment
```

By default, outputs are saved under `figures/<experiment folder name>/`.

### Generated outputs

- `bridge_results.pdf`: individual cycle-duration plots and measurements
  versus device count, including resource usage, acquisition and write
  rates, latency, errors, payload throughput and processing time.
- `bridge_peak_analysis.pdf`: delay histograms, slow-cycle frequency,
  peak magnitude and cycle-timing diagnostics.
- Individual figures saved as PNG files.
- CSV summaries and input-file records.

A slow cycle defaults to more than **0.1 seconds above the median**
for its device count. The report also shows the percentage of cycles
more than **0.5 seconds above the median**.

To save only PDFs and summary tables, add `--no-images`.

View all available options:

```bash
python plotting/plot_bridge_results.py --help
```

Measurement files are not modified. Reusing an output folder overwrites
reports with matching filenames.

## Interpreting measurements

- Process CPU usage of 100% corresponds to one logical CPU.
- RAM measurements are process resident memory.
- P5–P95 bands describe variability across samples.
- ZeroMQ payload throughput excludes network protocol overhead.
- Good tag quality alone does not establish data freshness.
- Diagnostic monitoring adds overhead to the Gateway.