#!/usr/bin/env python3
"""Run the dune_dscs asyncio bridge against N WIB emulators and record diagnostics.

This is the new-bridge version of bridge/ignition_pybridge_diagnostic.py. The
bridge code (src/dune_dscs/bridge.py) is used unchanged. It is instrumented
from outside:

  * Bridge.metrics.record is wrapped: every completed device poll (one full
    device read, all protobuf groups) is recorded with its queue/query/publish/
    total/lateness timings and its error.
  * BoardClient.exchange is wrapped: every ZMQ request-reply round trip is
    timed and its payload size counted. This matches the old "request".

The new bridge has no global polling cycle; each device has its own task and
period. A row in bridge_N<N>.csv therefore describes one fixed time WINDOW
(default: one poll period, so every device is normally polled once per row).

Outputs in --output-dir (never overwritten):
  bridge_N<N>.csv            one row per measured window
  bridge_N<N>.yaml           the exact bridge configuration used
  bridge_N<N>_settings.json  run settings, software versions, start/end time
  bridge_metrics_N<N>.json   the bridge's own --metrics snapshot (lifetime totals)
"""

import argparse
import asyncio
import csv
import json
import math
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import yaml
from google.protobuf.message import DecodeError

from dune_dscs import bridge as bridge_module
from dune_dscs.bridge_clients import BoardClient
from dune_dscs.metrics import ProcessSampler

HERE = Path(__file__).resolve().parent
STRESS = HERE.parent                # archive/stress_test/: results go here
REPO = HERE.parents[2]              # repository root
DEFAULT_TEMPLATE = REPO / "examples" / "bridge-varying.yaml"
# The stress test serves OPC UA on its own port, so it does not clash with another bridge
# on the same host (those use 4840). Change it with STRESS_ENDPOINT or --endpoint.
DEFAULT_ENDPOINT = os.environ.get("STRESS_ENDPOINT") or "opc.tcp://127.0.0.1:4841/dune/"
DECODE_ERRORS = (ValueError, TypeError, LookupError, AttributeError, DecodeError)

COLUMNS = [
    "time_utc", "window", "devices", "variables", "window_s",
    "cpu_percent", "ram_mb", "threads", "file_descriptors",
    # Device polls (one poll = complete read of one device, all message groups).
    "polls", "successes", "timeouts", "comm_errors", "decode_errors", "failure_percent", "error_types",
    "devices_polled", "devices_ok", "devices_stale", "max_value_age_s", "p95_value_age_s",
    "acquisitions_per_s", "node_writes", "node_writes_per_s", "opcua_writes",
    # ZMQ request-reply round trips (old "request").
    "zmq_requests", "mean_request_ms", "request_median_ms", "request_p95_ms", "request_p99_ms",
    "request_max_ms", "zmq_tx_payload_kB_s", "zmq_rx_payload_kB_s",
    # Bridge per-poll timings (new).
    "query_mean_ms", "query_median_ms", "query_p95_ms", "query_p99_ms", "query_max_ms",
    "queue_mean_ms", "queue_p95_ms", "queue_max_ms",
    "publish_total_ms", "publish_mean_ms", "publish_p95_ms",
    "total_mean_ms", "total_p95_ms", "total_max_ms",
    "lateness_mean_ms", "lateness_p95_ms", "lateness_max_ms", "overruns",
    "loop_lag_mean_ms", "loop_lag_p95_ms", "loop_lag_max_ms",
]


def percentile(values, percent):
    """Linear interpolation, the same definition as the old diagnostic."""
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (position - lower) * (values[upper] - values[lower])


def mean(values):
    return sum(values) / len(values) if values else None


def load_hosts(path):
    hosts = []
    for line in Path(path).read_text().splitlines():
        parts = line.split("#", 1)[0].split()
        if parts:
            hosts.append((parts[0], parts[1]))
    if not hosts:
        raise ValueError(f"no hosts in {path}")
    return hosts


def build_config(args):
    """Colleague's WIB device (variables, period, timeout) repeated over the fleet."""
    template = yaml.safe_load(Path(args.template).read_text())
    base = next((d for d in template["devices"] if d["kind"] == "wib"), None)
    if base is None:
        raise ValueError(f"no WIB device in {args.template}")
    hosts = load_hosts(args.hosts)
    if args.devices > len(hosts) * args.per_host:
        raise ValueError(f"N={args.devices} needs more than {args.per_host} emulators on {len(hosts)} hosts")
    period = args.period if args.period is not None else base.get("period", 1.0)
    devices = []
    for index in range(args.devices):
        name, address = hosts[index % len(hosts)]
        port = args.base_port + index // len(hosts)
        devices.append({"id": f"wib-{index + 1:04d}", "kind": "wib",
                        "endpoint": f"tcp://{address}:{port}", "period": period,
                        "variables": base["variables"]})
    config = {
        "endpoint": args.endpoint,
        "timeout": args.timeout if args.timeout is not None else template.get("timeout", 2.0),
        "concurrency": args.concurrency if args.concurrency is not None else template.get("concurrency", 32),
        "devices": devices,
    }
    return config, hosts, period


def source_state():
    try:
        commit = subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(REPO), "status", "--porcelain", "src"], text=True))
        return {"commit": commit, "src_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "src_dirty": None}


class Recorder:
    """Collects poll and round-trip samples; take() hands over one window."""

    def __init__(self, device_ids, loop):
        self.loop = loop
        self.device_ids = device_ids
        self.started = loop.time()
        self.last_ok = {}           # device id -> loop time of last successful poll
        self.ever_ok = set()
        self.reset()

    def reset(self):
        self.polls = []             # (device id, timings, error)
        self.requests_ms = []
        self.tx = self.rx = 0
        self.lag_ms = []

    def poll(self, device, timings, error):
        self.polls.append((device.id, timings, error, len(device.variables)))
        if error is None:
            self.last_ok[device.id] = self.loop.time()
            self.ever_ok.add(device.id)

    def take(self):
        window = (self.polls, self.requests_ms, self.tx, self.rx, self.lag_ms)
        self.reset()
        return window

    def value_ages(self):
        now = self.loop.time()
        return [now - self.last_ok.get(device, self.started) for device in self.device_ids]


def instrument(bridge, recorder):
    original_record = bridge.metrics.record

    def record(device, timings, error):
        original_record(device, timings, error)
        recorder.poll(device, timings, error)

    bridge.metrics.record = record  # Instance attribute; Bridge._poll calls self.metrics.record.

    original_exchange = BoardClient.exchange

    async def exchange(self, payload):
        recorder.tx += len(payload)
        started = time.perf_counter()
        reply = await original_exchange(self, payload)
        recorder.requests_ms.append((time.perf_counter() - started) * 1000)
        recorder.rx += len(reply)
        return reply

    BoardClient.exchange = exchange


def make_row(number, window_number, window_s, sample, window, ages, period, variables):
    polls, requests, tx, rx, lags = window
    timeouts = comm = decode = successes = node_writes = opcua_writes = 0
    error_types = {}
    devices_polled, devices_ok = set(), set()
    timing = {key: [] for key in ("query_ms", "queue_ms", "publish_ms", "total_ms", "start_lateness_ms")}
    for device_id, timings, error, nvars in polls:
        devices_polled.add(device_id)
        for key in timing:
            timing[key].append(timings[key])
        # Bridge._poll writes every variable (Good or Bad) + Available + LastError (+2 on success).
        opcua_writes += nvars + 2
        if error is None:
            successes += 1
            devices_ok.add(device_id)
            node_writes += nvars
            opcua_writes += 2
            continue
        error_types[type(error).__name__] = error_types.get(type(error).__name__, 0) + 1
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            timeouts += 1
        elif isinstance(error, DECODE_ERRORS):
            decode += 1
        else:
            comm += 1
    failures = timeouts + comm + decode
    q, qu, pub, tot, late = (timing[k] for k in ("query_ms", "queue_ms", "publish_ms", "total_ms",
                                                   "start_lateness_ms"))
    return {
        "time_utc": datetime.now(timezone.utc).isoformat(), "window": window_number,
        "devices": number, "variables": variables, "window_s": round(window_s, 6),
        "cpu_percent": sample.get("cpu_percent_one_core"),
        "ram_mb": round(sample["rss_mib"] * 1.048576, 2) if "rss_mib" in sample else None,  # MiB -> MB
        "threads": sample.get("threads"), "file_descriptors": sample.get("file_descriptors"),
        "polls": len(polls), "successes": successes, "timeouts": timeouts, "comm_errors": comm,
        "decode_errors": decode, "failure_percent": 100 * failures / len(polls) if polls else None,
        "error_types": ";".join(f"{k}:{v}" for k, v in sorted(error_types.items())),
        "devices_polled": len(devices_polled), "devices_ok": len(devices_ok),
        "devices_stale": sum(age > 2 * period for age in ages),
        "max_value_age_s": max(ages) if ages else None, "p95_value_age_s": percentile(ages, 95),
        "acquisitions_per_s": successes / window_s, "node_writes": node_writes,
        "node_writes_per_s": node_writes / window_s, "opcua_writes": opcua_writes,
        "zmq_requests": len(requests), "mean_request_ms": mean(requests),
        "request_median_ms": percentile(requests, 50), "request_p95_ms": percentile(requests, 95),
        "request_p99_ms": percentile(requests, 99), "request_max_ms": max(requests, default=None),
        "zmq_tx_payload_kB_s": tx / 1000 / window_s, "zmq_rx_payload_kB_s": rx / 1000 / window_s,
        "query_mean_ms": mean(q), "query_median_ms": percentile(q, 50), "query_p95_ms": percentile(q, 95),
        "query_p99_ms": percentile(q, 99), "query_max_ms": max(q, default=None),
        "queue_mean_ms": mean(qu), "queue_p95_ms": percentile(qu, 95), "queue_max_ms": max(qu, default=None),
        "publish_total_ms": sum(pub), "publish_mean_ms": mean(pub), "publish_p95_ms": percentile(pub, 95),
        "total_mean_ms": mean(tot), "total_p95_ms": percentile(tot, 95), "total_max_ms": max(tot, default=None),
        "lateness_mean_ms": mean(late), "lateness_p95_ms": percentile(late, 95),
        "lateness_max_ms": max(late, default=None),
        "overruns": sum(t > period * 1000 for t in tot),
        "loop_lag_mean_ms": mean(lags), "loop_lag_p95_ms": percentile(lags, 95),
        "loop_lag_max_ms": max(lags, default=None),
    }


async def lag_loop(recorder):
    loop = asyncio.get_running_loop()
    while True:
        due = loop.time() + 0.1
        await asyncio.sleep(0.1)
        recorder.lag_ms.append(max(0.0, (loop.time() - due) * 1000))


async def run(args, config, config_path, period, csv_path, settings_path, settings):
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    metrics_path = args.output_dir / f"bridge_metrics_N{args.devices}.json"
    bridge = bridge_module.Bridge(config, metrics_path, args.metrics_interval)
    recorder = Recorder([d.id for d in config.devices], loop)
    instrument(bridge, recorder)
    sampler = ProcessSampler(os.getpid())
    variables = sum(len(d.variables) for d in config.devices)
    window_s = args.window if args.window is not None else period
    helpers = []
    written = 0

    async def wait(seconds):
        """Sleep, but return True early on stop or if a polling task died."""
        watched = [asyncio.ensure_future(stop.wait()), *bridge.tasks]
        done, _ = await asyncio.wait(watched, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        watched[0].cancel()
        for task in done & set(bridge.tasks):
            task.result()
            raise RuntimeError(f"bridge polling task stopped: {task.get_name()}")
        return stop.is_set()

    with open(csv_path, "x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        stream.flush()
        try:
            await bridge.start()
            helpers.append(asyncio.create_task(lag_loop(recorder)))
            print(f"Bridge PID {os.getpid()} serving {config.endpoint}: N={args.devices}, "
                  f"{variables} variables, period {period} s, timeout {config.timeout} s, "
                  f"concurrency {config.concurrency}", flush=True)
            print(f"=== Warm-up {args.warmup:.0f} s; Ndevices: {args.devices} ===", flush=True)
            if await wait(args.warmup):
                return written
            never = [d for d in config.devices if d.id not in recorder.ever_ok]
            settings["devices_without_success_in_warmup"] = [d.endpoint for d in never]
            if never:
                listing = ", ".join(d.endpoint for d in never[:10]) + (" ..." if len(never) > 10 else "")
                print(f"WARNING: {len(never)}/{args.devices} devices never answered in warm-up: {listing}",
                      flush=True)
                if args.require_all:
                    raise RuntimeError("not all emulators answered during warm-up (are they running?)")
            recorder.take()
            sampler.sample()  # CPU baseline for the first window.
            print(f"Warm-up finished. Measuring windows of {window_s} s.", flush=True)
            started = previous = loop.time()
            number = 0
            while args.windows == 0 or number < args.windows:
                number += 1
                if await wait(max(0.0, started + number * window_s - loop.time())):
                    break  # Discard the incomplete window, like an interrupted old cycle.
                now = loop.time()
                row = make_row(args.devices, number, now - previous, sampler.sample(), recorder.take(),
                               recorder.value_ages(), period, variables)
                previous = now
                writer.writerow(row)
                stream.flush()
                written += 1
                fmt = lambda v, f: "-" if v is None else format(v, f)  # noqa: E731
                print(f"Window {number}/{args.windows or 'inf'}: polls {row['polls']} "
                      f"ok {row['successes']} fail {fmt(row['failure_percent'], '.1f')}% | "
                      f"req p50 {fmt(row['request_median_ms'], '.2f')} ms | "
                      f"lateness max {fmt(row['lateness_max_ms'], '.0f')} ms | "
                      f"CPU {fmt(row['cpu_percent'], '.1f')}% | RAM {fmt(row['ram_mb'], '.1f')} MB", flush=True)
        finally:
            for task in helpers:
                task.cancel()
            await asyncio.gather(*helpers, return_exceptions=True)
            await bridge.close()
            settings.update(finished_utc=datetime.now(timezone.utc).isoformat(), windows_written=written,
                            interrupted=stop.is_set())
            settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return written


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--devices", type=int, required=True, help="number of emulators to poll")
    parser.add_argument("--windows", type=int, default=60, help="measured windows after warm-up (0: until stopped)")
    parser.add_argument("--window", type=float, help="window length in s (default: the poll period)")
    parser.add_argument("--warmup", type=float, default=30, help="warm-up seconds (default 30)")
    parser.add_argument("--output-dir", type=Path, default=STRESS / "results" / "new_bridge")
    parser.add_argument("--hosts", type=Path, default=HERE / "hosts.txt")
    parser.add_argument("--per-host", type=int, default=100, help="emulators per host (default 100)")
    parser.add_argument("--base-port", type=int, default=5555)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE,
                        help="config whose WIB variables/period/timeout are used (default bridge-varying.yaml)")
    parser.add_argument("--period", type=float, help="override poll period (template: 5 s)")
    parser.add_argument("--timeout", type=float, help="override device read timeout (template: 10 s)")
    parser.add_argument("--concurrency", type=int, help="override concurrent reads (template: 32)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help=f"OPC UA endpoint the bridge serves (default {DEFAULT_ENDPOINT}; env STRESS_ENDPOINT)")
    parser.add_argument("--metrics-interval", type=float, default=5, help="bridge JSON snapshot period")
    parser.add_argument("--require-all", action="store_true",
                        help="abort after warm-up if any emulator never answered")
    args = parser.parse_args()
    if args.devices < 1 or args.windows < 0:
        parser.error("--devices must be positive and --windows nonnegative")
    for name in ("warmup",):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            parser.error(f"--{name} must be finite and nonnegative")
    if args.window is not None and (not math.isfinite(args.window) or args.window <= 0):
        parser.error("--window must be positive")
    args.output_dir = args.output_dir.resolve()
    return args


def raise_file_limit(devices):
    """Each device keeps a ZMQ socket (about 2 file descriptors). The usual soft limit of
    1024 open files is reached near N = 500; raise it to the hard limit for this process."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    wanted = hard if hard != resource.RLIM_INFINITY else max(soft, 65536)
    if soft != resource.RLIM_INFINITY and soft < wanted:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
            soft = wanted
        except (ValueError, OSError) as error:
            print(f"WARNING: could not raise the open-file limit from {soft}: {error}", flush=True)
    if soft != resource.RLIM_INFINITY and soft < 3 * devices + 100:
        print(f"WARNING: open-file limit {soft} is low for N={devices} (about {3 * devices + 100} needed)",
              flush=True)
    return soft, hard


def main():
    args = parse_arguments()
    file_limit = raise_file_limit(args.devices)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    n = args.devices
    csv_path = args.output_dir / f"bridge_N{n}.csv"
    config_path = args.output_dir / f"bridge_N{n}.yaml"
    settings_path = args.output_dir / f"bridge_N{n}_settings.json"
    metrics_path = args.output_dir / f"bridge_metrics_N{n}.json"
    for path in (csv_path, config_path, settings_path, metrics_path):
        if path.exists():
            sys.exit(f"Existing file: {path}\nChoose another --output-dir for a new experiment.")
    try:
        raw, hosts, period = build_config(args)
        with config_path.open("x") as stream:
            stream.write(f"# Generated by {Path(__file__).name} for N={n}.\n")
            yaml.safe_dump(raw, stream, sort_keys=False, width=120)
        config = bridge_module.load_config(config_path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        sys.exit(f"Configuration error: {error}")
    settings = {
        "N": n, "started_utc": datetime.now(timezone.utc).isoformat(), "host": platform.node(),
        "pid": os.getpid(), "python": platform.python_version(),
        "packages": {p: metadata.version(p) for p in ("asyncua", "pyzmq", "protobuf", "pysnmp")},
        "source": source_state(), "template": str(Path(args.template).resolve()),
        "hosts": [{"name": h, "address": a} for h, a in hosts], "base_port": args.base_port,
        "per_host": args.per_host, "period_s": period, "timeout_s": config.timeout,
        "concurrency": config.concurrency, "endpoint": config.endpoint,
        "variables_per_device": len(config.devices[0].variables),
        "window_s": args.window if args.window is not None else period,
        "warmup_s": args.warmup, "windows_requested": args.windows,
        "metrics_interval_s": args.metrics_interval,
        "open_file_limit": {"soft": file_limit[0], "hard": file_limit[1]},
        "csv_notes": {
            "window": "fixed time window; replaces the old polling cycle",
            "polls": "completed device polls (one poll = all protobuf groups of one device)",
            "zmq_requests/request_*": "single ZMQ request-reply round trips (old 'request'), successful only",
            "query_*": "complete device read incl. failures/timeouts (bridge metric query_ms)",
            "cpu_percent": "bridge process over the window, 100% = one logical CPU",
            "ram_mb": "RSS in MB (10^6 bytes), as in the old CSV",
            "node_writes": "measurement values written with Good quality",
            "opcua_writes": "all OPC UA writes incl. bad-quality values and status nodes",
            "devices_stale": "devices whose last successful poll is older than 2 periods",
        },
    }
    try:
        written = asyncio.run(run(args, config, config_path, period, csv_path, settings_path, settings))
    except RuntimeError as error:
        sys.exit(f"ERROR: {error}")
    print(f"Saved {written} windows to {csv_path}")
    if args.windows and written < args.windows:
        sys.exit(130)


if __name__ == "__main__":
    main()
