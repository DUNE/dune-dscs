# Mainz Slow Controls Stress Tests

Stress tests for the Python ZeroMQ-to-OPC-UA bridge and the Ignition
Gateway using distributed device emulators.

Each emulator provides three values: one temperature and two voltages.
The tests increase the number of devices and record performance,
resource usage and communication reliability.

## Directory structure

```text
stress_test/
├── results/       # Measurements grouped by test run
├── figures/       # Generated plots and summary tables
├── logs/          # Logs retained from previous runs, if present
├── .runtime/      # Emulator process records, created by the launcher
├── README.md
└── Scripts and configuration files
```

Results, figures and runtime files are local outputs and should remain
excluded from Git.

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

Run the following on each emulator host:

```bash
cd ~/dune-dscs/stress_test
bash create_emulators.sh
```

The launcher starts 100 emulators on TCP ports 5555–5654.
Emulator output is discarded, so no log files are created.

One runtime file per host is stored under `.runtime/`. It records the
PID, process start time and port of each launched emulator.

Stop the recorded emulators on the same host:

```bash
bash stop_emulators.sh
```

The stop script verifies ownership, process start time and command before
sending SIGTERM. It waits up to ten seconds and retains records for
processes it could not stop.

Do not delete runtime records while the corresponding emulators are
running. The stop script manages instances started by the new launcher.

## Bridge stress test

Run a single device-count configuration:

```bash
python ignition_pybridge_diagnostic.py --devices 10 --cycles 300
```

Run the configured bridge test sequence:

```bash
bash run_bridge_test.sh
```

Check the device counts and cycle count in the runner before starting.

The bridge records:

- Polling-cycle duration.
- Process CPU usage and resident memory.
- Request attempts, successes, timeouts and errors.
- Successful acquisition rate.
- Request latency statistics.
- ZeroMQ payload throughput in both directions.
- OPC UA variable write count and rate.
- Response parsing and node-update time.

## Ignition stress test

Before starting:

1. Confirm the emulators are running on the configured hosts.
2. Confirm the Ignition Gateway is running and its trial or licence is active.
3. Confirm its OPC UA connection points to the bridge host.
4. Set the diagnostic timer to the intended enabled or disabled state.
5. Check the device counts, warm-up and measured cycle count in the runner.

Run on the host containing the Ignition Gateway:

```bash
bash run_ignition_tests.sh
```

`monitor_ignition.py` measures the local Gateway Java process's CPU usage
and resident memory. The bridge diagnostic code measures the bridge's
own resources.

When enabled, the Ignition Gateway timer script records tag completeness,
tag quality, OPC UA connection state and diagnostic collection time.
It uses a shared control file to identify the active run.

The runner supports resuming tests. Its completion check uses the
corresponding bridge CSV, so an existing completed CSV can cause a
device count to be skipped.

## Results and plots

Keep each test run in its own folder under `results/`. Preserve the
distinction between:

- Timer-enabled and timer-disabled runs.
- Original and cached diagnostic scripts.
- Complete runs and partial repeats.

Store generated figures and summary tables under `figures/`.

Plotting scripts include:

- `stress_test_result.py`
- `plot_ignition_results.py`
- `plot_bridge_ignition.py`
- `plot_timer_comparison.py`

Check each script's input and output paths before running it.

## Paths after reorganisation

Code has moved from `Tutorials/workshop2026` to `stress_test`.
Measurements and figures have also been reorganised.

Update remaining references to the old locations in:

- Python scripts and Bash runners.
- Plotting input and output paths.
- The Ignition Gateway timer script stored in Designer.

The Ignition timer's base directory should be:

```python
BASE = "/uni-mainz.de/homes/lgoncalve/dune-dscs/stress_test"
```

## Interpreting measurements

- Process CPU usage of 100% corresponds to one logical CPU.
- RAM measurements are process resident memory.
- P5–P95 bands describe variability across samples.
- ZeroMQ payload throughput excludes network protocol overhead.
- Good tag quality alone does not establish data freshness.
- Diagnostic monitoring adds overhead to the Gateway.