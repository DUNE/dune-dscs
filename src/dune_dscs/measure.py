"""Measure OPC UA reads and optional local bridge PIDs; save a new JSON report."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import itertools
import json
import math
import platform
import subprocess
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

from asyncua import Client, ua

from .bridge import load_config, validate
from .metrics import Distribution, ProcessSampler, write_json


def request_timed_out(error):
    return isinstance(error, (TimeoutError, asyncio.TimeoutError)) or (
        isinstance(error, ua.UaStatusCodeError) and error.code == ua.StatusCodes.BadTimeout)


def source_state():
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                         stderr=subprocess.DEVNULL, text=True).strip()
        changes = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
        return {"commit": commit, "dirty": bool(changes)}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


async def measure(config, duration=30, workers=4, chunk_size=100, timeout=2, pids=(), resource_interval=1):
    validate(config)
    if any(not math.isfinite(v) or v <= 0 for v in (duration, timeout, resource_interval)):
        raise ValueError("duration, timeout and resource interval must be positive and finite")
    if any(type(v) is not int or v < 1 for v in (workers, chunk_size)):
        raise ValueError("workers and chunk size must be positive integers")
    samplers = {pid: ProcessSampler(pid) for pid in dict.fromkeys(pids)}
    histories = {pid: deque(maxlen=256) for pid in samplers}
    resource_counts = Counter()
    resource_stats = {pid: {key: Distribution() for key in
                      ("cpu_percent_one_core", "rss_mib", "threads", "file_descriptors")}
                      for pid in samplers}
    latencies = {name: Distribution(4096) for name in ("query_ms", "successful_query_ms", "failed_query_ms")}
    ages = {name: Distribution(4096) for name in ("good_value_age_ms", "bad_value_age_ms")}
    counts, errors, bad_codes = Counter(), Counter(), Counter()
    stop = asyncio.Event()

    def sample_resources():
        for pid, sampler in samplers.items():
            value = sampler.sample()
            histories[pid].append({"time_utc": datetime.now(timezone.utc).isoformat(), **value})
            resource_counts[pid] += 1
            if value["status"] == "running":
                for key, stats in resource_stats[pid].items():
                    if value[key] is not None:
                        stats.add(value[key])

    async def resource_loop():
        while not stop.is_set():
            sample_resources()
            try:
                await asyncio.wait_for(stop.wait(), resource_interval)
            except asyncio.TimeoutError:
                pass

    report = {"schema_version": 1, "scope": "opcua_read_requests", "status": "completed",
              "started_utc": datetime.now(timezone.utc).isoformat(), "host": platform.node(),
              "python": platform.python_version(), "source": source_state(),
              "dependencies": {name: importlib.metadata.version(name) for name in ("asyncua", "pyzmq", "pysnmp")},
              "endpoint": config.endpoint, "namespace": config.namespace,
              "device_count": len(config.devices), "device_counts": dict(Counter(d.kind for d in config.devices)),
              "settings": {"duration_seconds": duration, "workers": workers, "chunk_size": chunk_size,
                           "timeout_seconds": timeout, "resource_interval_seconds": resource_interval},
              "connect_ms": None, "connect_error": None, "connect_timeouts": 0}
    resources = asyncio.create_task(resource_loop())
    client = Client(config.endpoint, timeout=timeout)
    client.session_timeout = 600_000
    connected, tasks = False, []
    started = None
    connect_started = time.perf_counter()
    try:
        await asyncio.wait_for(client.connect(), timeout)
        connected = True
        index = await asyncio.wait_for(client.get_namespace_index(config.namespace), timeout)
        report["connect_ms"] = (time.perf_counter() - connect_started) * 1000
        nodes = [client.get_node(ua.NodeId(f"Devices.{d.id}.{name}", index))
                 for d in config.devices for name in d.variables]
        report["node_count"] = len(nodes)
        chunks = itertools.cycle([nodes[i:i + chunk_size] for i in range(0, len(nodes), chunk_size)])
        started = time.perf_counter()
        deadline = started + duration

        async def read_worker():
            while time.perf_counter() < deadline:
                chunk = next(chunks)
                request_started = time.perf_counter()
                counts["requests"] += 1
                counts["values_requested"] += len(chunk)
                success = False
                try:
                    try:
                        values = await asyncio.wait_for(client.read_attributes(chunk), timeout)
                    finally:
                        elapsed = (time.perf_counter() - request_started) * 1000
                    if len(values) != len(chunk):
                        raise ValueError("incomplete OPC UA response")
                    success = True
                    counts["successful_requests"] += 1
                    now = datetime.now(timezone.utc)
                    for value in values:
                        good = value.StatusCode.is_good()
                        counts["good_values" if good else "bad_values"] += 1
                        if not good:
                            bad_codes[value.StatusCode.name] += 1
                        if value.SourceTimestamp is not None:
                            ages["good_value_age_ms" if good else "bad_value_age_ms"].add(
                                (now - value.SourceTimestamp).total_seconds() * 1000)
                except asyncio.CancelledError:
                    counts["failed_requests"] += 1
                    counts["cancelled_requests"] += 1
                    errors["CancelledError"] += 1
                    raise
                except (OSError, asyncio.TimeoutError, ua.UaError, ValueError) as exc:
                    counts["failed_requests"] += 1
                    counts["timeouts"] += request_timed_out(exc)
                    errors[type(exc).__name__] += 1
                finally:
                    latencies["query_ms"].add(elapsed)
                    latencies["successful_query_ms" if success else "failed_query_ms"].add(elapsed)

        tasks = [asyncio.create_task(read_worker()) for _ in range(workers)]
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        report["status"] = "interrupted"
    except (OSError, asyncio.TimeoutError, ua.UaError, ValueError) as exc:
        report.update(status="connection_failed", connect_error=f"{type(exc).__name__}: {exc}",
                      connect_ms=(time.perf_counter() - connect_started) * 1000,
                      connect_timeouts=int(request_timed_out(exc)))
    finally:
        elapsed = time.perf_counter() - started if started is not None else 0
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if connected:
            try:
                await asyncio.wait_for(client.disconnect(), timeout)
            except (OSError, asyncio.TimeoutError, ua.UaError):
                report["disconnect_error"] = True
        stop.set()
        await resources
        sample_resources()
        report.update(finished_utc=datetime.now(timezone.utc).isoformat(), elapsed_seconds=elapsed,
                      counts={name: counts[name] for name in ("requests", "successful_requests", "failed_requests",
                              "timeouts", "cancelled_requests", "values_requested", "good_values", "bad_values")},
                      errors=dict(errors), bad_status_codes=dict(bad_codes),
                      successful_requests_per_second=counts["successful_requests"] / elapsed if elapsed else 0,
                      good_values_per_second=counts["good_values"] / elapsed if elapsed else 0,
                      **{name: values.snapshot() for name, values in {**latencies, **ages}.items()},
                      resources={str(pid): {"samples": resource_counts[pid], "history_capacity": 256,
                          "statistics": {key: stats.snapshot() for key, stats in resource_stats[pid].items()},
                          "history": list(histories[pid])} for pid in samplers})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--endpoint")
    parser.add_argument("--kind", action="append", choices=("wib", "daphne", "pdu"))
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=2)
    parser.add_argument("--pid", type=int, action="append", default=[], help="local PID to sample; repeat for several")
    parser.add_argument("--output", required=True, help="new JSON report; must not exist")
    args = parser.parse_args()
    if Path(args.output).exists():
        parser.error("output already exists; choose a new report name")
    try:
        config = load_config(args.config, args.kind)
        if args.endpoint:
            config.endpoint = args.endpoint
        report = asyncio.run(measure(config, args.duration, args.workers, args.chunk_size, args.timeout, args.pid))
        report["configuration_sha256"] = hashlib.sha256(Path(args.config).read_bytes()).hexdigest()
        write_json(args.output, report, replace=False)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"report": args.output, "status": report["status"], **report["counts"]}))
    raise SystemExit(0 if report["status"] == "completed" else 130 if report["status"] == "interrupted" else 1)


if __name__ == "__main__":
    main()
