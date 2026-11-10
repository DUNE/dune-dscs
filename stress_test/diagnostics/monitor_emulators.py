#!/usr/bin/env python3
"""Write total CPU and RSS samples for this user's emulator processes."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

SAMPLE_INTERVAL_S = 1


def parse_arguments():
    """Accept the runner's stop file or the original duration argument."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target", nargs="?", default="300",
        help="Shared stop-file path or number of one-second samples.",
    )
    args = parser.parse_args()

    try:
        sample_limit = int(args.target)
    except ValueError:
        return Path(args.target), None

    if sample_limit < 1:
        parser.error("The number of samples must be at least 1.")

    return None, sample_limit


def find_emulators():
    """Find and prime resource measurements for the current emulators."""
    emulators = []

    for process in psutil.process_iter(["cmdline", "uids"]):
        try:
            command = process.info["cmdline"] or []
            owner = process.info["uids"]

            if (
                owner is not None
                and owner.real == os.getuid()
                and any(
                    Path(argument).name == "zmq_emulator.py"
                    for argument in command
                )
            ):
                process.cpu_percent(None)
                emulators.append(process)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not emulators:
        raise RuntimeError("No accessible emulator processes for your user.")

    return emulators


def main():
    """Sample the initial emulator processes until stopped or limited."""
    stop_file, sample_limit = parse_arguments()

    try:
        emulators = find_emulators()
        writer = csv.writer(sys.stdout)
        writer.writerow(["time_utc", "emulators", "cpu_percent", "rss_mb"])
        sys.stdout.flush()
        samples = 0

        while sample_limit is None or samples < sample_limit:
            if stop_file is not None and stop_file.exists():
                break

            time.sleep(SAMPLE_INTERVAL_S)

            if stop_file is not None and stop_file.exists():
                break

            cpu_percent = 0.0
            memory_bytes = 0
            count = 0

            for process in emulators:
                try:
                    if not process.is_running():
                        continue

                    process_cpu = process.cpu_percent(None)
                    process_memory = process.memory_info().rss
                    cpu_percent += process_cpu
                    memory_bytes += process_memory
                    count += 1

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if count == 0:
                raise RuntimeError("No monitored emulators remain accessible.")

            writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                count,
                round(cpu_percent, 2),
                round(memory_bytes / 1_000_000, 2),
            ])
            sys.stdout.flush()
            samples += 1

    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, psutil.Error) as error:
        print(f"Emulator monitoring failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
