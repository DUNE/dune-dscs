# Emulator-increasing test with the new dune_dscs bridge

This is a repeat of the old bridge-only stress test (`diagnostics/run_bridge_test.sh` on the
`mainz-stress-test` branch). It uses the current code in `src/dune_dscs`:

- **Emulators:** `python -m dune_dscs.emulator wib --vary`, 100 per Weber host on ports
  5555–5654. Device i is on host `i % 10`, port `5555 + i // 10`, the same layout as before.
- **Bridge:** `dune_dscs.bridge.Bridge`, unchanged. It uses the WIB device from
  `examples/bridge-varying.yaml`: 14 variables, period 5 s, timeout 10 s, concurrency 32.

These scripts need the branch with `src/dune_dscs` checked out (`mainz-test-stand/develop`).
Don't switch branches while emulators or the bridge are running.

## Files

| File | Purpose |
|---|---|
| `hosts.txt` | Emulator hosts and addresses, in device order |
| `emulator_fleet.py` | Start, stop or check the emulators on the host it runs on |
| `fleet.sh` | Runs `emulator_fleet.py` on every host over ssh (optional) |
| `check_fleet.py` | Checks from the bridge host that all 1000 emulators answer |
| `bridge_diagnostic.py` | Runs the bridge for one N and writes `bridge_N<N>.csv` |
| `run_bridge_test.sh` | Runs the series N = 10, 110, … 1000 |
| `plot_new_bridge_results.py` | Plots (adapted from `plotting/plot_bridge_results.py`) |

## 0. One-time setup

Your home folder is shared by all hosts, so you only need to do this once, on any host.

```bash
# Environment for the emulators and the bridge (the old opcua-env has no pysnmp).
python3 -m venv ~/DSCS/dscs-env
~/DSCS/dscs-env/bin/pip install -e ~/dune-dscs
~/DSCS/dscs-env/bin/python -c "import dune_dscs.bridge, dune_dscs.emulator.wib; print('ok')"
```

Plots use the old environment `~/DSCS/opcua-env`, which has pandas and matplotlib.

## 1. Start the emulators by hand on each host

Repeat these steps on **every** host in `hosts.txt`: Weber02, 03, 06, 07, 09, 10, 11, 12, 13, 14.

```bash
ssh etapweberXX            # or log in at the machine
cd ~/dune-dscs/stress_test
git -C ~/dune-dscs branch --show-current     # must be mainz-test-stand/develop
```

**a) Stop the old emulators** if they are still running. The old `zmq_emulator.py` uses
the same ports 5555–5654.

```bash
pgrep -u "$USER" -fc 'emulators/zmq_emulator.py'     # how many old emulators are running
pkill -u "$USER" -f 'emulators/zmq_emulator.py'      # stop them
ss -ltn | grep -cE ':(55[5-9][0-9]|56[0-5][0-9]) '   # must print 0: ports are free
```

If the last command does not print 0, someone else's process is using the ports. Find it
with `ss -ltnp | grep 5555`.

**b) Start the 100 new WIB emulators.**

```bash
~/DSCS/dscs-env/bin/python new_bridge/emulator_fleet.py start
```

The output should be `etapweberXX: 100 WIB emulators running on ports 5555-5654.`
The emulators keep running after you log out. Each one writes a log to
`stress_test/.runtime/dscs_emulator_logs/<host>/wib_<port>.log`.

**c) Check on that host.**

```bash
~/DSCS/dscs-env/bin/python new_bridge/emulator_fleet.py status   # 100/100 recorded emulators running
ss -ltn | grep -cE ':(55[5-9][0-9]|56[0-5][0-9]) '                # 100
```

To stop them later, run this on each host:

```bash
~/DSCS/dscs-env/bin/python new_bridge/emulator_fleet.py stop
```

Alternative: if password-less ssh to every address in `hosts.txt` works, `new_bridge/fleet.sh
start|status|stop` does step b, c or the stop on all hosts at once. It does not do step a.

## 2. Verification procedure (run on the bridge host)

Run every step from `~/dune-dscs/stress_test` on the host that will run the bridge.
Don't start the full test until all steps pass.

**Step 1. All emulators answer with the new protocol.**

```bash
~/DSCS/dscs-env/bin/python new_bridge/check_fleet.py --verbose
```

Expected: `OK` for all 10 hosts, then `1000/1000 emulators answer as new WIB emulators.` (exit 0).

| Result for a host | Meaning | Fix |
|---|---|---|
| `other/old 100` | The old `zmq_emulator.py` is still running there | Step 1a, then 1b on that host |
| `no-answer 100` | Nothing is running, or a firewall blocks it | Step 1b on that host; check `emulator_fleet.py status` |
| `no-answer` for some ports | Some emulators died | Look at their logs; run `stop` then `start` on that host |

**Step 2. Short bridge test with one device per host.**

```bash
~/DSCS/dscs-env/bin/python new_bridge/bridge_diagnostic.py --devices 10 \
    --warmup 15 --windows 3 --require-all --output-dir results/new_bridge_smoke_N10
```

Expected: no `WARNING` line. Every `Window` line shows `ok 10 fail 0.0%` and a request
median of a few ms.

**Step 3. Short bridge test with the full fleet.**

```bash
~/DSCS/dscs-env/bin/python new_bridge/bridge_diagnostic.py --devices 1000 \
    --warmup 30 --windows 3 --require-all --output-dir results/new_bridge_smoke_N1000
```

Expected: about `polls 1000 ok 1000 fail 0.0%` per window. Step 3 shows that every
emulator is reachable through the bridge, not only through `check_fleet.py`.
A run aborted with `not all emulators answered during warm-up` names the missing
endpoints; go back to step 1 for those hosts.

**Step 4. Check the output files of a smoke run.**

```bash
ls results/new_bridge_smoke_N10
# bridge_N10.csv  bridge_N10.yaml  bridge_N10_settings.json  bridge_metrics_N10.json
cut -d, -f2,10-15 results/new_bridge_smoke_N10/bridge_N10.csv     # window, polls ... failure_percent
```

`bridge_N10_settings.json` records the period, timeout, concurrency, git commit and the
list `devices_without_success_in_warmup`, which should be empty.

Smoke-test folders are separate experiments. Delete them, or leave them out of the plots.

## 3. Run the full test

```bash
new_bridge/run_bridge_test.sh        # N = 10 110 ... 1000; 60 windows (5 min) + 30 s warm-up each, about 1 h
```

Runner options are set through environment variables: `DEVICE_COUNTS`, `WINDOWS`, `WARMUP`,
`PERIOD`, `TIMEOUT`, `CONCURRENCY`, `RESULTS_DIR` (default `results/new_bridge_scaling`).
The runner refuses to overwrite existing results. Each N runs with `--require-all`, so a
missing emulator stops the series instead of producing bad data. The terminal output of
each N is also saved in `bridge_N<N>.log`.

A single N can run until you press Ctrl-C (endurance):
`~/DSCS/dscs-env/bin/python new_bridge/bridge_diagnostic.py --devices 1000 --windows 0`.

## 4. Plot

```bash
~/DSCS/opcua-env/bin/python new_bridge/plot_new_bridge_results.py \
    --data-dir results/new_bridge_scaling --compare-dir results/bridge_no_sleep
```

The report goes to `figures/new_bridge_scaling/`: `bridge_results.pdf`, PNGs and summary CSVs.
`--extra-diagnostic-pictures` adds a time series for each N.

## 5. Stop the emulators

Run `emulator_fleet.py stop` on each host, as in step 1, or `new_bridge/fleet.sh stop`.

## What changed compared with the old diagnostic

The new bridge has **no polling cycle**. Each device has its own asyncio task, which polls
every `period` seconds, and at most `concurrency` devices are read at the same time.
One CSV row is therefore a fixed **time window** (default: one period). In each window
every device is normally polled once.

| Old column | New column | Note |
|---|---|---|
| `cycle`, `cycle_s` | `window`, `window_s` | `window_s` stays about the same as N grows. Overload shows in the columns below. |
| `attempts` | `polls` | One poll = complete read of one device (4 ZMQ requests) |
| `timeouts`, `send_errors`, `other_errors` | `timeouts`, `comm_errors`, `decode_errors` | Same categories the bridge uses for its OPC UA status codes |
| `mean_request_ms`, `request_*_ms` | same names | One ZMQ round trip, successful only: the same definition as before |
| `parse_total_ms` | — | Parsing happens inside the device read (`query_*_ms`) |
| `update_total_ms` | `publish_total_ms` | Also writes status nodes |
| `cpu_percent` | `cpu_percent` | Over the window. There is no "excluding sleep" value because there is no global sleep. |
| `ram_mb` | `ram_mb` | MB (10^6 bytes), as before |
| — | `query_*`, `queue_*`, `lateness_*`, `overruns`, `devices_stale`, `max_value_age_s`, `loop_lag_*`, `threads`, `file_descriptors` | New overload indicators |

Each N also writes `bridge_N<N>.yaml` (the exact config), `bridge_N<N>_settings.json`
(settings, versions, git commit), `bridge_N<N>.log`, and the bridge's own
`bridge_metrics_N<N>.json` (lifetime totals from `dune_dscs.metrics`).

When comparing with old results, keep in mind that each device now does 4 requests per
poll every 5 s, while the old test did 1 request per device every cycle (about 1 s or less).
CPU and throughput therefore compare different workloads. Request latency and RAM compare directly.
