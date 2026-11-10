#!/usr/bin/env python3
"""Write Ignition Gateway process CPU and memory samples to standard output."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

GATEWAY_CLASS = "com.inductiveautomation.catapult.Catapult"
SAMPLE_INTERVAL_S = 1


def find_gateway_process():
    """Find the single Ignition Gateway process owned by the current user."""
    matches = []

    for process in psutil.process_iter(["cmdline", "uids"]):
        try:
            command = process.info["cmdline"] or []
            owner = process.info["uids"]

            if (
                owner is not None
                and owner.real == os.getuid()
                and GATEWAY_CLASS in command
            ):
                matches.append(process)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one Ignition Gateway process for your user; "
            f"found {len(matches)}. Run on the Gateway host."
        )

    return matches[0]


def main():
    """Sample Gateway resources until the runner creates the stop file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("devices", type=int, help="Device count for this run.")
    parser.add_argument("stop_file", type=Path, help="Runner's stop marker.")
    parser.add_argument("ready_file", type=Path, help="Startup ready marker.")
    args = parser.parse_args()

    if args.devices < 1:
        parser.error("devices must be at least 1")

    try:
        process = find_gateway_process()
        process.cpu_percent(None)
        writer = csv.writer(sys.stdout)

        if os.environ.get("WRITE_HEADER") == "1":
            writer.writerow([
                "time_utc", "N", "pid", "cpu_percent", "rss_mb",
            ])

        sys.stdout.flush()
        args.ready_file.touch()

        while not args.stop_file.exists():
            time.sleep(SAMPLE_INTERVAL_S)

            if args.stop_file.exists():
                break
            if not process.is_running():
                raise psutil.NoSuchProcess(process.pid)

            cpu_percent = process.cpu_percent(None)
            memory_mb = process.memory_info().rss / 1_000_000

            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                args.devices,
                process.pid,
                cpu_percent,
                round(memory_mb, 2),
            ])
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, psutil.Error) as error:
        print(f"Ignition monitoring failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
