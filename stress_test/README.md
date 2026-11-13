# Mainz Slow Controls Stress Tests

Stress tests for the Python ZeroMQ-to-OPC-UA bridge and the Ignition
Gateway using distributed device emulators. Each emulator supplies one
temperature and two voltages. Tests vary the number of devices and record
performance, resource usage and communication reliability.

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
│   ├── run_bridge_emulator_tests.sh
│   └── run_ignition_tests.sh
├── ignition_monitoring_scripts/
│   └── ignition_monitoring_scripts/ignition_tag_diagnostics_cached.py
│   └── ignition_tag_diagnostics_configurable.py
│   └── ignition_monitoring_scripts/ignition_tag_diagnostics_uncached.py
├── plotting/
│   ├── plot_bridge_results.py
│   ├── plot_ignition_results.py
│   ├── plot_bridge_ignition_comparison.py
│   └── plot_timer_cached_comparisons.py
├── results/            # Measurements grouped by experiment
├── figures/            # Generated reports, images and summaries
├── .runtime/           # Process records, readiness markers and locks
├── ignition_test_control.json  # Generated bridge–Gateway control file
├── zmq_em.proto
├── zmq_em_pb2.py
├── .gitignore
└── README.md
```

`results/`, `figures/`, `.runtime/` and `ignition_test_control.json` are
runtime outputs and should remain excluded from Git. Runtime files and
output folders are created as needed.

The configurable Gateway script replaces the separate cached and
uncached timer scripts. The four plotting files above replace the older
plotting entry points. Keep the plotting files together because they
reuse shared helper functions.

## Environment and host configuration

### Create the Python environment

Run on a Weber computer using Python 3.10 or newer:

```bash
mkdir -p "$HOME/DSCS"
python3 -m venv "$HOME/DSCS/opcua-env"
source "$HOME/DSCS/opcua-env/bin/activate"

python -m pip install --upgrade pip
python -m pip install \
    "protobuf==7.36.2" \
    pyzmq \
    opcua \
    PyYAML \
    psutil \
    pandas \
    numpy \
    matplotlib
```

The package `pyzmq` provides the Python `zmq` module.
The current bridge uses `opcua`; `asyncua` is not required.

The quotes around `"protobuf==7.36.2"` keep the version specification
as one shell argument. If using `>=` instead, quotes are essential
to prevent shell output redirection.

The Mainz computers share the user's home directory, so the environment
is available at the same path on each host. Activate it in each terminal:

```bash
source "$HOME/DSCS/opcua-env/bin/activate"
cd "$HOME/dune-dscs/stress_test"
```

### Install the Protobuf compiler without sudo

The compiler is only needed when regenerating `zmq_em_pb2.py`.
The following binary is for the Linux x86-64 Weber computers:

```bash
mkdir -p "$HOME/DSCS/tools/protoc"
cd "$HOME/DSCS/tools/protoc"

wget \
    https://github.com/protocolbuffers/protobuf/releases/download/v36.2/protoc-36.2-linux-x86_64.zip

unzip protoc-36.2-linux-x86_64.zip

export PROTOC="$HOME/DSCS/tools/protoc"
"$PROTOC/bin/protoc" --version
```

`PROTOC` is set for the current terminal. Set it again in a new terminal
when needed.

After changing `zmq_em.proto`, regenerate the Python module:

```bash
cd "$HOME/dune-dscs/stress_test"
export PROTOC="$HOME/DSCS/tools/protoc"

"$PROTOC/bin/protoc" \
    --proto_path=. \
    --proto_path="$PROTOC/include" \
    --python_out=. \
    zmq_em.proto
```
### Activating the python environment 

Run the commands below from the `stress_test` root:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
```

The Bash test runners use `~/DSCS/opcua-env/bin/python` by default.
Override `PYTHON` when using another environment.

Python dependencies are `pyzmq`, `protobuf`, `opcua`, `PyYAML` and `psutil`.
Plotting also requires `pandas`, `numpy` and `matplotlib`. The generated
`zmq_em_pb2.py` must be compatible with the installed Protobuf runtime;
regenerate it when changing `zmq_em.proto`.

### Open the Ignition Gateway from another computer

Run the SSH tunnel on your Mac or other client computer:

```bash
ssh -N -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:8088:134.93.128.243:8088 \
    weber02
```

Then open:

```text
http://127.0.0.1:8088
```

This forwards local port 8088 through Weber02 to the Ignition Gateway
on Weber09 (`134.93.128.243`), assuming its HTTP port is 8088.

If the Gateway uses port 8089 instead, use:

```bash
ssh -N -o ExitOnForwardFailure=yes \
    -L 127.0.0.1:8088:134.93.128.243:8089 \
    weber02
```

The browser address remains `http://127.0.0.1:8088`.

`weber02` must be a working SSH hostname or alias on the client computer.
Leave the terminal open while using the tunnel. No terminal output after
authentication is normal. Press Ctrl+C to close the tunnel.




### Emulator hosts and capacity

The current diagnostic configuration uses Weber03, Weber06, Weber07,
Weber02, Weber09, Weber10, Weber11, Weber12 and Weber14, in that order.
Device selection rotates through the hosts, then increments the emulator
number. Emulator 1 uses port 5555; emulator 100 uses port 5654.

Keep these configurations consistent:

- `EMULATOR_HOSTS` in `bridge/ignition_pybridge_diagnostic.py`.
- `HOSTS` in `diagnostics/run_bridge_emulator_tests.sh`.
- `hosts` inside the configurable Ignition Gateway script.

With nine hosts and 100 emulators per host, the deployment provides
**900 emulators**. Although the diagnostic bridge accepts N from 1 to
1000, larger loads require additional running emulators and matching
configuration. Do not assume the command-line limit establishes capacity.

## Start and stop emulators

Run on each configured emulator host:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
bash emulators/create_emulators.sh
```

The launcher starts 100 emulators on ports 5555–5654 and discards their
output. It does not create emulator log files. Process records are stored
under `.runtime/`, separately for each host.

Stop the recorded instances on the same host:

```bash
bash emulators/stop_emulators.sh
```

The stop script verifies ownership, process start time and command before
sending SIGTERM. It waits up to ten seconds and retains records for
processes it could not stop. Keep the records while the corresponding
emulators are running. These launchers manage instances started by the
runtime-record launcher.

## Bridge

### Files and configuration

| File under `bridge/` | Purpose |
|---|---|
| `ignition_pybridge.py` | Continuously polls devices listed in the device YAML. |
| `ignition_pybridge_diagnostic.py` | Generates a device list for N and records measured polling cycles. |
| `zmq_devices_config.py` | Loads the continuous bridge's device configuration. |
| `zmq_sensor_config.py` | Loads the sensor-field configuration. |
| `zmq_devices.yaml` | Devices for the continuous bridge. |
| `zmq_sensors.yaml` | Sensor fields and number of values per field. |

Both bridge versions use `zmq_em_pb2.py` at the `stress_test` root.
The diagnostic bridge selects devices through `EMULATOR_HOSTS`, rather
than reading `zmq_devices.yaml`.

An entry in the continuous bridge's device YAML looks like:

```yaml
zmqdevice:
  - tpc: 3
    dev: 1
    host: "134.93.131.35"
    port: 5555
```

Start the required emulators before either bridge. Only one bridge can
listen on port 4840 on a given host at a time.

### Continuous bridge

```bash
python bridge/ignition_pybridge.py
```

This exposes readings without writing stress-test measurements. It uses
a one-second delay before each polling cycle and a two-second receive
timeout per request. Press Ctrl+C to stop it.

### Diagnostic bridge: one device count

Run from the `stress_test` root:

```bash
python bridge/ignition_pybridge_diagnostic.py \
    --devices 10 \
    --cycles 300 \
    --warmup 30 \
    --output-dir results/bridge_only
```

| Option | Meaning and default |
|---|---|
| `--devices` | Required device count, from 1 to 1000; check actual emulator capacity. |
| `--cycles` | Measured polling cycles; default `10`. Use `0` to run until stopped. |
| `--warmup` | Warm-up duration in seconds; default `30`. |
| `--output-dir` | Measurement destination; default `stress_test/results`. |
| `--timer-enabled` | Enable recurring Gateway diagnostic collection; default `true`. Requires the configurable Gateway timer. |
| `--cache-enabled` | Reuse Gateway tag paths; default `true`. |
| `--wait-for-ignition` | Wait for Gateway readiness before warm-up; off unless supplied. |
| `--setup-timeout` | Readiness timeout in seconds; default `60`. |
| `--cpu-profile` | Record CPU samples and polling-phase transitions; off unless supplied. |
| `--cpu-sample-interval` | CPU profiling interval in seconds; default `0.1`. Used with `--cpu-profile`. |

The example creates `results/bridge_only/bridge_N10.csv`. Output folders
are created automatically. Existing bridge CSVs are never overwritten.

The current diagnostic bridge uses a **one-second receive timeout per
request**, configured by `REQUEST_TIMEOUT_MS = 1000`.

Warm-up is measured in seconds and completes at a polling-cycle boundary.
Warm-up cycles update nodes but are excluded from the normal bridge CSV.
Measured cycle durations include the one-second polling delay.
300 cycles are not necessarily 300 seconds.

The bridge writes the device count, run ID, active state, diagnostic
settings and selected output directory to `ignition_test_control.json`
at the `stress_test` root. A folder name alone does not enable or disable
Gateway diagnostics.

Press Ctrl+C to stop the bridge.



### CPU measurements: including sleep, excluding sleep and external sampling

The diagnostic bridge automatically saves both cycle CPU averages in
`bridge_N<number>.csv`. No additional option is needed:

| Column | Measurement window |
|---|---|
| `cpu_percent` | Full cycle, including the one-second polling sleep. |
| `cpu_active_percent` | Device requests, response parsing and node updates, excluding the polling sleep. |
| `cycle_s` | Duration of the full cycle, including sleep. |
| `active_s` | Duration of the active polling and update window. |

Both CPU percentages are calculated as process CPU time divided by wall
time for their respective windows, multiplied by 100. Process CPU time
includes all bridge threads. The active window still includes waiting
for emulator responses; it is not a measure of CPU execution time alone.
These measurements exclude warm-up cycles.

Use the full-cycle average to report normal resource consumption. Use
the active average to describe CPU usage while polling and updating
nodes. Keep the definitions consistent when comparing experiments.

For a time profile independent of cycle boundaries, use the external
`diagnostics/monitor_bridge_cpu.py` monitor. It must be saved in that
location before running the following command. Run both processes on
the same computer and choose an unused output folder:

```bash
cd ~/dune-dscs/stress_test
source ~/DSCS/opcua-env/bin/activate

python bridge/ignition_pybridge_diagnostic.py \
    --devices 900 \
    --cycles 300 \
    --warmup 30 \
    --output-dir results/bridge_900_cpu_comparison &

bridge_pid=$!

python diagnostics/monitor_bridge_cpu.py \
    --pid "$bridge_pid" \
    --interval 0.2 \
    --output results/bridge_900_cpu_comparison/external_cpu.csv

wait "$bridge_pid"
```

The `&` starts the bridge in the background. `$!` supplies its PID to
the monitor automatically. The monitor samples approximately every
0.2 seconds, without waiting for the bridge loop, and stops when the
bridge exits. Ctrl+C stops the foreground monitor; the background
bridge continues running.

The experiment folder contains:

- `bridge_N900.csv`: per-cycle diagnostics with both CPU averages.
- `external_cpu.csv`: timestamps, elapsed time, actual sampling interval,
  bridge PID and CPU percentage, including setup and warm-up while the
  monitor is running.

External samples include any sleep, waiting or work occurring within
each interval. They are interval averages, like htop, rather than
instantaneous CPU readings. Short intervals can produce discrete CPU
levels because Linux process CPU counters have limited resolution.
Use `--interval 1` for a smoother-resolution overview at one sample per
second. Neither option applies additional smoothing.

The external monitor does not require `--cpu-profile`. The optional
internal profiler below is a separate way to record CPU intervals and
cycle boundaries.

To compare all three CPU measurements, run:

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/bridge_900_cpu_comparison \
    --devices 900 \
    --cpu-comparison \
    --output-dir figures/bridge_900_cpu_comparison
```

This mode creates only two plots in `bridge_cpu_comparison.pdf`, with
individual PNGs: CPU comparison by cycle and CPU versus elapsed time.
External samples are weighted by their overlap with each cycle; cycles
with less than 99% external coverage are omitted from that external
curve. Alignment is approximate because the bridge CSV timestamp is
recorded near the cycle end. The time plot shows the external samples
and both bridge averages over their respective windows. Use
`--external-cpu /path/to/file.csv` to select another external CSV.



#### Optional CPU profiling within a cycle

Use a separate short run:

```bash
python bridge/ignition_pybridge_diagnostic.py \
    --devices 10 \
    --cycles 10 \
    --warmup 5 \
    --cpu-profile \
    --cpu-sample-interval 0.1 \
    --output-dir results/bridge_cpu_profile
```

In addition to the normal per-cycle CSV, this creates:

```text
results/bridge_cpu_profile/bridge_cpu_profile_N10.csv
```

The profile records:

- Whole-process CPU averages over the actual sampling intervals.
- Cycle boundaries and warm-up markers.
- Polling-phase transitions: sleep, requests, response parsing,
  OPC UA node updates and bookkeeping.

CPU samples use an independent `psutil.Process` object, so they do not
reset the normal per-cycle CPU counter. Sampling intervals may span
several phases or cross cycle boundaries.

Generate the profile plots:

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/bridge_cpu_profile \
    --profile-cycles 1 2 3 \
    --output-dir figures/bridge_cpu_profile
```

Profile plots are included in `bridge_results.pdf` and saved as individual
PNGs. Without `--profile-cycles`, the first three complete measured cycles
are selected when profile data is available.

The CPU graph represents all bridge threads. The phase timeline shows
what the polling loop was doing; it does not directly attribute CPU usage
to individual phases.

Profiling adds overhead and produces phase records for each request.
Use short diagnostic runs initially. Profiling remains disabled during
normal runs, and the automated runners do not currently forward these
optional profiling arguments.

Only one bridge can use port 4840 on a host at a time.

### OPC UA connection

Both bridge versions expose:

```text
opc.tcp://<bridge-host>:4840/freeopcua/server/
```

Use `127.0.0.1` when Ignition and the bridge run on the same computer;
otherwise use the bridge host's IP address. Configure anonymous
access, Security Policy `None` and Security Mode `None`.

Sensor node identifiers use the following format:

```text
TPC<tpc>/WIB<device>/<field>/<index>
```

For example, `TPC3/WIB1/Temp1/0`.

### Bridge measurements

Each `bridge_N<number>.csv` contains one row per measured cycle:

- UTC timestamp, cycle number, device count and variable count.
- Polling-cycle duration, process CPU usage and resident memory.
- Request attempts, successes, receive timeouts and errors.
- Failure percentage and successful acquisition rate.
- Mean, median, P95 and P99 latency of successful requests.
- ZeroMQ transmit and receive payload throughput.
- OPC UA variable-write count and write rate.
- Total response-parsing and node-update time.

## Automated test runners

Edit `DEVICE_COUNTS` in the selected runner to choose the tested loads.
The other settings listed below can be supplied as environment variables.

| Runner under `diagnostics/` | Default device counts | Default results folder |
|---|---|---|
| `run_bridge_test.sh` | `110` | `results/bridge_only/` |
| `run_bridge_emulator_tests.sh` | `10 110 210 310 410 510 610 710 810 900` | `results/emulator_bridge/` |
| `run_ignition_tests.sh` | `10 110 210 310 410 510 610 710 810 900` | Depends on diagnostic mode; default `results/timer_cached/`. |

All three runners default to `CYCLES=300` measured cycles and
`WARMUP=30` seconds. Relative `RESULTS_DIR` paths are resolved from the
`stress_test` root, because the runners change to that directory.

### Bridge-only sequence

```bash
bash diagnostics/run_bridge_test.sh
```

This starts no Ignition or emulator resource monitors. It refuses to
overwrite existing bridge CSVs and does not resume partial runs.

For a shorter run in another folder:

```bash
CYCLES=10 WARMUP=5 RESULTS_DIR=results/bridge_validation \
bash diagnostics/run_bridge_test.sh
```

For isolated bridge measurements, disable the Gateway diagnostic timer
and disconnect OPC UA clients that should not contribute to the load.
The runner does not stop existing Gateway activity.

### Bridge and emulator-resource sequence

```bash
bash diagnostics/run_bridge_emulator_tests.sh
```

Preparation:

1. Start emulators on every configured host.
2. Match `HOSTS` to the bridge's host list.
3. Make the shared repository and Python environment available at the
   same absolute paths on every host.
4. Confirm passwordless SSH from the runner host to remote emulator hosts.

For example:

```bash
ssh -o BatchMode=yes lgoncalve@134.93.131.35 hostname
```

The local host is monitored directly; remote hosts are monitored through
SSH. `REMOTE_USER` defaults to the current username and can be overridden.

For a custom experiment:

```bash
CYCLES=10 WARMUP=5 RESULTS_DIR=results/emulator_bridge_validation \
bash diagnostics/run_bridge_emulator_tests.sh
```

Outputs include `bridge_N<number>.csv` and one emulator-resource CSV per
host and device count, such as `emulators_N110_Weber02.csv`.

`monitor_emulators.py` records the accessible emulator processes found
at monitor startup, including idle emulators. Each sample contains UTC
time, process count, summed CPU usage and summed resident memory.
Summed RSS can count shared pages more than once.

The runner waits for samples from every host before starting the bridge.
Emulator monitoring includes startup and warm-up; bridge CSVs contain
measured cycles only. At the end, the monitors stop and emulators remain
running. Errors appear in the terminal; no separate `.err` files are
created. The runner protects existing files and does not resume partial
runs. Choose another `RESULTS_DIR` for an independent experiment.

## Ignition Gateway setup

The Ignition runner measures the local Gateway Java process. Run it on
the Gateway host, Weber09 in the Mainz setup. This avoids remote process
monitoring; Ignition itself does not require the bridge on the same host.

### Install the configurable timer

Use:

```text
ignition_monitoring_scripts/ignition_tag_diagnostics_configurable.py
```

In Ignition Designer:

1. Open the stress-test project.
2. Expand **Scripting → Gateway Events → Timer**.
3. Create or open a timer named `BridgeStressMonitor`.
4. Replace its function with the complete `handleTimerEvent()` function
   from the configurable file. Keep one function definition.
5. Set **Delay** to `5000` ms, **Delay Type** to `Fixed Delay`,
   **Threading** to `Dedicated` and **Enabled** to checked.
6. Save the project.

Use only one diagnostic timer. Fixed Delay waits five seconds after an
execution finishes before starting the next one.

Inside the installed function, check:

```python
BASE_DIR = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
OPC_SERVER = "bridge leonor 09"
```

`BASE_DIR` must be accessible to the Gateway process. `OPC_SERVER` must
match its configured OPC UA connection name. Match the `hosts` ordering
to the diagnostic bridge, and confirm the Ignition trial or licence is
active.

Keep the timer enabled in Designer for every automated mode below.
`TIMER_ENABLED=false` disables recurring diagnostic collection through
the control file; it does not uncheck the Designer timer.

## Ignition test modes

Run commands from the `stress_test` root on the Ignition Gateway host:

```bash
source ~/DSCS/opcua-env/bin/activate
cd ~/dune-dscs/stress_test
```

Keep the configurable Gateway timer enabled in Designer. The runner
controls recurring diagnostic collection through the shared control file.

The runner supports:

- A finite sequence of device counts.
- An endurance test at one fixed device count, without a cycle limit.

Defaults are `ENDURANCE=false`, `TIMER_ENABLED=true` and
`CACHE_ENABLED=true`.

| Collection | Caching | Default finite-test folder |
|---|---|---|
| Disabled | Ignored | `results/diagnostics_disabled/` |
| Enabled | Off | `results/timer_uncached/` |
| Enabled | On | `results/timer_cached/` |

### Disabled diagnostic collection

```bash
TIMER_ENABLED=false \
bash diagnostics/run_ignition_tests.sh
```

Ignition creates the expected tags and checks initial readiness.
Once ready, the timer skips recurring collection but continues checking
the control file periodically. This differs from disabling the entire
timer in Designer.

### Enabled, uncached collection

```bash
TIMER_ENABLED=true CACHE_ENABLED=false \
bash diagnostics/run_ignition_tests.sh
```

The Gateway rebuilds tag lists and browses paths on each diagnostic
execution. Tags are created when a new run starts.

### Enabled, cached collection

```bash
TIMER_ENABLED=true CACHE_ENABLED=true \
bash diagnostics/run_ignition_tests.sh
```

This is also the default:

```bash
bash diagnostics/run_ignition_tests.sh
```

The Gateway builds and validates paths once per run, then reuses them.
Cached completeness counts come from the initial check; tag quality and
connection state are sampled during recurring collection. An end-of-run
path audit is written to the Gateway logger.

### Finite tests: device counts, cycles and warm-up

Edit `DEVICE_COUNTS` in the runner to select the finite test sequence.

Override cycles, warm-up and output directory using environment variables:

```bash
TIMER_ENABLED=true CACHE_ENABLED=false \
CYCLES=10 WARMUP=5 RESULTS_DIR=results/my_experiment \
bash diagnostics/run_ignition_tests.sh
```

`CYCLES` counts measured polling cycles. `WARMUP` is measured in seconds.

The runner passes the selected output folder to the bridge and Gateway
script. Relative results paths are resolved from the `stress_test` root.

Use a new folder for an independent repeat:

```bash
TIMER_ENABLED=true CACHE_ENABLED=true \
RESULTS_DIR=results/timer_cached_repeat \
bash diagnostics/run_ignition_tests.sh
```

### Endurance test: run until stopped or a process fails

Endurance mode runs one fixed load without a cycle limit:

```bash
ENDURANCE=true DEVICE_COUNT=1000 \
TIMER_ENABLED=true CACHE_ENABLED=true \
RESULTS_DIR=results/endurance_cached \
bash diagnostics/run_ignition_tests.sh
```

Before using this mode, the diagnostic bridge must support
`--cycles 0` as unlimited execution.

| Setting | Endurance default |
|---|---|
| `DEVICE_COUNT` | `1000` |
| `WARMUP` | `30` seconds |
| `POST_FAILURE_SECONDS` | `60` seconds |
| Cycle limit | None; the runner passes `--cycles 0` |
| Automatic restart | Disabled |

`DEVICE_COUNT` replaces the finite `DEVICE_COUNTS` sequence.
`CYCLES` does not limit an endurance run. Confirm that enough emulators
are running for the selected load.

Collection and caching options work in endurance mode too. For example:

```bash
ENDURANCE=true DEVICE_COUNT=1000 \
TIMER_ENABLED=true CACHE_ENABLED=false \
RESULTS_DIR=results/endurance_uncached \
bash diagnostics/run_ignition_tests.sh
```

If `RESULTS_DIR` is omitted, endurance folders default to:

- `results/endurance_diagnostics_disabled/`
- `results/endurance_timer_uncached/`
- `results/endurance_timer_cached/`

Always use a fresh folder for another endurance attempt. Existing
measurements and experiment settings are protected from overwriting.

#### Error recording and failure behaviour

Request timeouts and other request errors are counted in the bridge CSV.
Individual request errors do not automatically stop the test.

`experiment.log` records bridge output, exceptions, process exits and
timestamped runner events.

If the bridge exits, the runner preserves its partial CSV and continues
Ignition resource monitoring for `POST_FAILURE_SECONDS`, provided that
monitor remains available.

If the resource monitor exits while the bridge is running, the runner
stops the bridge and preserves the measurements. Processes are not
automatically restarted.

The post-failure period monitors Gateway process resources. It does not
guarantee continued Gateway tag diagnostics after the bridge ends its
active run.

A running process can also become unresponsive without exiting.
Endurance mode does not automatically detect every stalled cycle or
sustained communication failure; inspect timestamps and error counts.

#### Watch and stop the test

From another terminal:

```bash
tail -f ~/dune-dscs/stress_test/results/endurance_cached/experiment.log
```

Press Ctrl+C in the runner terminal to stop the test cleanly.
Measurements are retained. Ctrl+C in the `tail` terminal only stops
watching the log.

Keep the runner terminal connected, or run it inside a persistent
terminal session such as `tmux` if available.

### Sequence and output files

The runner starts resource monitoring and the bridge, waits for Good tag
quality and a connected OPC UA state, then performs warm-up before
recording measured cycles. Gateway readiness defaults to a 60-second
timeout.

| File in the selected experiment folder | Contents |
|---|---|
| `test_settings.json` | Device count settings, warm-up and diagnostic mode; endurance settings when applicable. |
| `bridge_N<number>.csv` | Bridge measurements for N. |
| `ignition_resources.csv` | Gateway process CPU and resident memory. |
| `ignition_tag_diagnostics.csv` | Periodic tag and connection diagnostics when collection is enabled. |
| `ignition_timer_profile.csv` | Per-operation elapsed and timer-thread CPU time when collection is enabled. |
| `experiment.log` | Terminal output, errors and runner events in endurance mode. |

Gateway process resources are measured by
`diagnostics/monitor_ignition.py`, not by the bridge or Gateway timer.
These samples include setup, warm-up and measured cycles. In endurance
mode, they may also include the post-failure period.

Bridge CSVs contain measured cycles only.

The control file stays at the `stress_test` root. Readiness status,
monitor markers and locks are stored under `.runtime/`.

### Resume an interrupted finite experiment

For finite tests, rerun the same command with the same settings and
`RESULTS_DIR`.

Completed configurations are skipped. An unfinished N has its previous
samples removed and is repeated. A failed finite run may have its
unfinished bridge CSV removed during cleanup.

Completion requires the expected bridge cycles and associated resource
samples. Enabled collection also requires tag-diagnostic and profiling
samples. A mismatch with saved experiment settings stops the runner.

Endurance tests do not use this resume behaviour. Their partial
measurements are preserved as failure evidence; start a new attempt
in a fresh results folder.

## Plotting results

All commands below run from the `stress_test` root. Select one experiment
per input folder; do not pool independent repeats under the same N.
Bridge inputs use exactly `bridge_N<number>.csv`. Suffixed repeats such
as `bridge_N900_1.csv` are not selected.

### Bridge-only report

By default, the plotting script generates figures with device count N
on the horizontal axis. These include CPU usage, memory, acquisition
rate, request latency, processing time and error counts.

The CPU comparison shows both measurements:

- **Including sleep:** median CPU usage across complete polling cycles.
- **Excluding sleep:** median CPU usage during requests, parsing and
  node updates, excluding the fixed polling sleep.

Each CPU curve has a shaded P5–P95 band describing variation across
cycles. These bands are not confidence intervals.

#### Summary plots versus N

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/bridge_cpu_both \
    --output-dir figures/bridge_summary
```

Individual profiles for each device count are excluded by default.

#### Include individual diagnostic plots

Add `--extra-diagnostic-pictures` to include cycle traces, histograms,
timing diagnostics and available CPU profiles for each device count:

```bash
python plotting/plot_bridge_results.py \
    --data-dir results/bridge_cpu_both \
    --extra-diagnostic-pictures \
    --output-dir figures/bridge_detailed
```

`--full-report` is an alias for `--extra-diagnostic-pictures`.

To select particular device counts, add:

```bash
--devices 110 510 1000
```

If internal CPU-profile CSVs are available, select the cycles to plot
with:

```bash
--profile-cycles 1 2 3
```

This requires `--extra-diagnostic-pictures`. Without an explicit cycle
selection, the first three complete measured cycles are used.

#### Outputs

Both modes save:

- `bridge_results.pdf`
- `bridge_peak_analysis.pdf`
- Individual PNG figures.
- Summary CSVs and input/settings records.

The CPU-versus-N comparison is named:

```text
cpu_including_vs_excluding_sleep_vs_N.png
cpu_including_vs_excluding_sleep_vs_N.pdf
```

Use `--no-images` to omit individual PNGs while retaining PDF reports.

Use separate output folders for summary and detailed reports. Existing
figures are not deleted automatically.

#### Slow-cycle analysis

A slow cycle defaults to more than 0.1 seconds above its run's median.
Use `--slow-threshold` to change this threshold.

A separate figure counts cycles more than 0.5 seconds above the median.

The timing breakdown assumes a one-second fixed polling sleep. Use
`--poll-sleep` if that delay has changed.


### Ignition-only report

```bash
python plotting/plot_ignition_results.py \
    --data-dir results/diagnostics_disabled \
    --output-dir figures/ignition_disabled
```

Required input: `ignition_resources.csv`.
Optional input: `ignition_tag_diagnostics.csv`.

This plots Gateway CPU and resident memory, high-CPU sample frequency,
and available tag quality, completeness, connection state and diagnostic
collection time. The main report is `ignition_results.pdf`.

No bridge files are needed. All recorded resource samples for each N are
used, including setup and warm-up if present. Collection time is elapsed
time for the diagnostic checks, not request latency or thread CPU time.

### Bridge–Ignition resource comparison

```bash
python plotting/plot_bridge_ignition_comparison.py \
    --bridge-dir results/bridge_only \
    --ignition-dir results/diagnostics_disabled \
    --output-dir figures/bridge_ignition_comparison
```

The bridge folder supplies `bridge_N<number>.csv`; the Ignition folder
supplies `ignition_resources.csv`. The report compares process CPU and
resident memory, retaining each component's available N values.

The output PDF is `bridge_ignition_comparison.pdf`. The selected folders
may represent separate experiments. Ignition statistics use all recorded
resource samples for each N, including setup and warm-up if present.

### Ignition enabled/disabled and cached/uncached comparisons

Use `plotting/plot_timer_cached_comparisons.py` for two or more cases.
Each `--case LABEL FOLDER` supplies one experiment and its legend label.
Despite the filename, it supports enabled/disabled comparisons too.

For new enabled and disabled experiments:

```bash
python plotting/plot_timer_cached_comparisons.py \
    --case Enabled results/timer_uncached \
    --case Disabled results/diagnostics_disabled \
    --output-dir figures/timer_enabled_vs_disabled
```

Here, Enabled means collection enabled without caching. To analyse the
historical enabled/disabled datasets instead, use the input folders
`results/timer_enabled_case` and `results/timer_disabled_complete`.
Historical disabled runs may have had the entire Designer timer disabled;
keep that distinction from the configurable runner's disabled mode.

For cached versus uncached experiments:

```bash
python plotting/plot_timer_cached_comparisons.py \
    --case Uncached results/timer_uncached \
    --case Cached results/timer_cached \
    --output-dir figures/timer_cached_vs_uncached
```

Both enabled/disabled and cached/uncached comparisons support multiple N
values. Omit `--devices` to analyse all available N values. To select
several, use a complete command such as:

```bash
python plotting/plot_timer_cached_comparisons.py \
    --case Uncached results/timer_uncached \
    --case Cached results/timer_cached \
    --devices 10 110 210 310 \
    --window measured \
    --output-dir figures/timer_selected_devices
```

Plots versus N retain each case's available counts. Detailed per-N plots
are generated for counts shared by all selected cases. Additional
`--case` arguments allow comparisons between three or more experiments.

For the existing N=900 cached and uncached runs:

```bash
python plotting/plot_timer_cached_comparisons.py \
    --case Uncached results/timer_original_N900 \
    --case Cached results/timer_cached_N900 \
    --devices 900 \
    --window measured \
    --output-dir figures/timer_cached_vs_uncached_N900
```

Each case requires `ignition_resources.csv`. Tag diagnostics are optional;
CPU and RAM comparisons work without them.

#### Measurement windows

- `--window all` is the default. It uses every recorded resource sample
  for each N, including setup and warm-up if present.
- `--window measured` reads `bridge_N<number>.csv` in each case folder.
  The first cycle's end timestamp minus its duration defines the start;
  the last cycle's timestamp defines the end. Samples outside that
  interval are excluded. Bridge metrics are not plotted in this report.

Use the same window policy for cases intended for comparison.

#### Comparison outputs

The selected output folder contains `ignition_timer_comparison.pdf`,
individual PNGs, `summary.csv` and `plot_settings.json`. Figures include:

- CPU and memory versus N, with median and P5–P95 bands.
- Mean CPU, P95 CPU and percentage of samples above the CPU threshold.
- Per-N CPU traces with identical main scales and labelled zooms.
- Per-N mean/P95 bars, CPU distributions and memory traces.
- Diagnostic collection-time and tag-quality comparisons when available.

### Plot options and scope

All four plotting scripts accept `--output-dir`, `--devices`, `--no-images`
and `--help`. `--no-images` keeps the PDFs and tables without individual
PNGs. To change the high-CPU threshold in Ignition reports or timer-case
comparisons, use `--spike-threshold`; the default is 50% process CPU.

Plots are saved under `figures/` by default. Rerunning into the same
output folder overwrites generated files with matching names; measurements
are never modified. Changing plotting options may leave older, differently
named figures in that folder.

These four plotters do not analyse the per-operation thread timings in
`ignition_timer_profile.csv` or the per-host emulator-resource CSVs.
Those measurements remain available for separate profiling analysis.

## Interpreting measurements

- Process CPU usage of 100% corresponds to one logical CPU. Summed emulator
  CPU can exceed 100% when several processes run concurrently.
- RAM is resident process memory. It is not JVM heap usage, and summed
  emulator RSS may count shared pages more than once.
- P5–P95 bands describe sample variability, not confidence intervals.
- Request P95/P99 values are per-cycle statistics; medians of them are not
  whole-run request percentiles.
- ZeroMQ payload throughput excludes transport and network overhead.
- Internal OPC UA writes do not establish delivery to an Ignition client.
- Connected status and good tag quality alone do not prove data freshness.
- Tag-quality snapshots are periodic; they do not establish continuous
  availability between samples.
- High-CPU percentages count threshold-exceeding samples, not distinct
  peak events. Slow-cycle percentages count individual qualifying cycles.
- Cached completeness counts describe the initial path check, whereas
  quality and connection are sampled during recurring collection.
- Timer-thread CPU time measures CPU used by that diagnostic thread.
  Gateway process CPU also includes other JVM threads and work.
- Diagnostic collection adds overhead to Ignition. Interpret resource
  comparisons using the documented mode, sample window and run history.
