# Mainz Slow Controls Stress Tests

Stress tests for the Python ZeroMQ-to-OPC-UA bridge and the Ignition
Gateway using distributed device emulators.

Each emulator provides three values: one temperature and two voltages.
The tests increase the number of devices and record performance,
resource usage and communication reliability.

## Directory structure

```text
stress_test/
├── bridge/
│   ├── ignition_pybridge.py
│   ├── ignition_pybridge_diagnostic.py
│   ├── bridge_diagnostics.py
│   ├── zmq_devices_config.py
│   ├── zmq_sensor_config.py
│   ├── zmq_devices.yaml
│   ├── zmq_devices_all.yaml
│   └── zmq_sensors.yaml
├── emulators/
│   ├── zmq_emulator.py
│   ├── create_emulators.sh
│   └── stop_emulators.sh
├── diagnostics/
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