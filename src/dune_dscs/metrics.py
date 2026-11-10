"""Bounded timing statistics and Linux process resource samples."""

import asyncio
import json
import logging
import math
import os
import tempfile
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)


class Distribution:
    """Lifetime count/mean/extrema; nearest-rank percentiles over a bounded tail."""

    def __init__(self, capacity=256):
        self.samples = deque(maxlen=capacity)
        self.count, self.total = 0, 0.0
        self.minimum, self.maximum = None, None

    def add(self, value):
        self.samples.append(value)
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def snapshot(self):
        values = sorted(self.samples)
        return {"count": self.count, "window_count": len(values), "window_capacity": self.samples.maxlen,
                "mean": self.total / self.count if self.count else None,
                "min": self.minimum, "max": self.maximum,
                **{f"p{q}": values[math.ceil(q / 100 * len(values)) - 1] if values else None
                   for q in (50, 95, 99)}}


class ProcessSampler:
    """One PID only. CPU 100% means one logical CPU; children are excluded."""

    def __init__(self, pid):
        if pid <= 0:
            raise ValueError("PID must be positive")
        self.pid, self.identity, self.previous = pid, None, None

    def sample(self):
        root = Path(f"/proc/{self.pid}")
        try:
            # comm can contain spaces and parentheses; fields after the final ')' are fixed.
            fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
            identity = fields[19]  # starttime, field 22
            if self.identity is not None and identity != self.identity:
                return {"pid": self.pid, "status": "pid_reused"}
            self.identity = identity
            now = time.monotonic()
            cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
            percent = None
            if self.previous is not None:
                elapsed = now - self.previous[0]
                percent = 100 * (cpu - self.previous[1]) / elapsed if elapsed else None
            self.previous = now, cpu
            status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines())
            rss = int(status["VmRSS"].split()[0]) / 1024
            peak = int(status["VmHWM"].split()[0]) / 1024
            descriptors = len(list((root / "fd").iterdir()))
            # Detect exit/reuse during the multi-file sample too.
            if (root / "stat").read_text().rsplit(")", 1)[1].split()[19] != identity:
                return {"pid": self.pid, "status": "pid_reused"}
            return {"pid": self.pid, "status": "running", "cpu_seconds": cpu,
                    "cpu_percent_one_core": percent, "rss_mib": rss, "peak_rss_mib": peak,
                    "threads": int(fields[17]), "file_descriptors": descriptors}
        except (OSError, KeyError, IndexError, ValueError) as exc:
            return {"pid": self.pid, "status": "unavailable", "error": type(exc).__name__}


def write_json(path, data, replace=True):
    """Publish complete JSON atomically. Saved measurement runs refuse overwrites."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, allow_nan=False)
            stream.write("\n")
            stream.close()
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class PollStats:
    def __init__(self):
        self.successes, self.failures, self.timeouts, self.overruns = 0, 0, 0, 0
        self.errors = Counter()
        self.timings = {name: Distribution() for name in
                        ("queue_ms", "query_ms", "publish_ms", "total_ms", "start_lateness_ms")}

    def record(self, timings, error, period):
        if error is None:
            self.successes += 1
        else:
            self.failures += 1
            self.timeouts += isinstance(error, (TimeoutError, asyncio.TimeoutError))
            self.errors[type(error).__name__] += 1
        self.overruns += timings["total_ms"] > period * 1000
        for key, value in timings.items():
            self.timings[key].add(value)

    def snapshot(self):
        return {"polls": self.successes + self.failures, "successes": self.successes,
                "failures": self.failures, "timeouts": self.timeouts, "overruns": self.overruns,
                "errors": dict(self.errors),
                **{name: values.snapshot() for name, values in self.timings.items()}}


class BridgeMetrics:
    def __init__(self, devices, path, interval):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("metrics interval must be positive and finite")
        self.path, self.interval = Path(path), interval
        self.started = time.monotonic()
        self.process = ProcessSampler(os.getpid())
        self.devices = {d.id: (d.kind, PollStats()) for d in devices}
        self.by_kind = {d.kind: PollStats() for d in devices}
        self.total = PollStats()
        self.loop_lag = Distribution()
        self.tasks = []

    def record(self, device, timings, error):
        for stats in (self.total, self.by_kind[device.kind], self.devices[device.id][1]):
            stats.record(timings, error, device.period)

    def snapshot(self):
        elapsed = time.monotonic() - self.started
        return {"schema_version": 1, "scope": "native_device_polls",
                "updated_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": elapsed,
                "process": self.process.sample(), "device_count": len(self.devices),
                "polls_per_second": self.total.timings["total_ms"].count / elapsed if elapsed else 0,
                "event_loop_lag_ms": self.loop_lag.snapshot(), "total": self.total.snapshot(),
                "by_kind": {kind: stats.snapshot() for kind, stats in self.by_kind.items()},
                "devices": {name: {"kind": kind, **stats.snapshot()}
                            for name, (kind, stats) in self.devices.items()}}

    async def flush(self):
        snapshot = self.snapshot()  # Copy counters on the event loop; only file I/O leaves it.
        writer = asyncio.create_task(asyncio.to_thread(write_json, self.path, snapshot))
        try:
            await asyncio.shield(writer)
        except asyncio.CancelledError:
            await writer  # Finish an in-progress write before publishing the final snapshot.
            raise

    async def start(self):
        self.started = time.monotonic()
        await self.flush()  # Fail early if the requested output cannot be written.
        self.tasks = [asyncio.create_task(self._lag_loop()), asyncio.create_task(self._report_loop())]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        try:
            await self.flush()
        except OSError:
            LOG.exception("Could not save the final bridge metrics")

    async def _lag_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            due = loop.time() + 0.1
            await asyncio.sleep(0.1)
            self.loop_lag.add(max(0, (loop.time() - due) * 1000))

    async def _report_loop(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.flush()
            except OSError:
                LOG.exception("Could not write bridge metrics; device polling continues")
