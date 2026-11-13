#!/usr/bin/env python3
"""Record bridge CPU usage independently of polling cycles."""

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/bridge_cpu_external.csv"),
    )
    args = parser.parse_args()

    if not 0 < args.interval < float("inf"):
        parser.error("--interval must be positive and finite.")

    process = psutil.Process(args.pid)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("x", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "time_utc",
            "elapsed_s",
            "interval_s",
            "pid",
            "cpu_percent",
        ])

        print(f"Monitoring PID {process.pid} every {args.interval} s.")
        print(f"Saving to {args.output.resolve()}")
        print("Press Ctrl+C to stop monitoring.")

        process.cpu_percent(None)
        start = previous = time.perf_counter()

        try:
            while True:
                time.sleep(args.interval)

                cpu = process.cpu_percent(None)
                now = time.perf_counter()

                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    round(now - start, 6),
                    round(now - previous, 6),
                    process.pid,
                    cpu,
                ])
                file.flush()
                previous = now

        except KeyboardInterrupt:
            print("\nMonitoring stopped.")
        except psutil.NoSuchProcess:
            print("\nBridge process exited.")


if __name__ == "__main__":
    main()