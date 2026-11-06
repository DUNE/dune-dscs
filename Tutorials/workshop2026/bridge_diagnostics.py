#!/usr/bin/env python3

import argparse
import csv
import time
from datetime import datetime, timezone
from tqdm import tqdm

import psutil

from zmq_devices_config import ZMQDevicesConfig
from zmq_sensor_config import ZMQSensorConfig


parser = argparse.ArgumentParser()
parser.add_argument("--pid", type=int)
parser.add_argument("--duration", type=float, default=300)
parser.add_argument("--interval", type=float, default=1)
args = parser.parse_args()

if args.interval <= 0 or args.duration < args.interval:
    parser.error("Require duration >= interval > 0.")

# Count configured devices and variables.
devices = list(ZMQDevicesConfig().get_devices())
sensors = ZMQSensorConfig()

variables_per_device = (
    sum(sensors.get_voltages().values())
    + sum(sensors.get_temperatures().values())
)
expected_variables = len(devices) * variables_per_device

print("Configured devices:", len(devices))
print("Variables per device:", variables_per_device)
print("Expected variables:", expected_variables)

if args.pid is not None:
    process = psutil.Process(args.pid)
    print("Monitoring:", process.pid, process.name())
    print("CPU: 100% = one logical CPU")

    filename = datetime.now(timezone.utc).strftime(
        "bridge_resources_%Y%m%dT%H%M%S_%fZ.csv"
    )
    print("Saving to:", filename)

    with open(filename, "x", newline="") as file, tqdm(
    total=int(args.duration / args.interval),
    desc="Monitoring bridge",
    unit="sample",
    ) as progress:
        writer = csv.writer(file)
        writer.writerow([
            "time_utc", "elapsed_s", "configured_devices",
            "expected_variables", "cpu_percent", "ram_mb"
        ])

        process.cpu_percent(None)  # Discard initial CPU reading.
        start = time.perf_counter()
        next_sample = start + args.interval
        end = start + args.duration

        try:
            while next_sample <= end:
                time.sleep(max(0, next_sample - time.perf_counter()))

                cpu = process.cpu_percent(None)
                ram = process.memory_info().rss / 1_000_000
                now = time.perf_counter()

                writer.writerow([
                    datetime.now(timezone.utc).isoformat(),
                    round(now - start, 3),
                    len(devices),
                    expected_variables,
                    cpu,
                    round(ram, 2),
                ])
                file.flush()
                progress.update(1)
                progress.set_postfix(cpu=f"{cpu:.1f}%", ram=f"{ram:.1f} MB")

                next_sample += args.interval
                while next_sample <= now:
                    next_sample += args.interval

        except KeyboardInterrupt:
            print("Monitoring stopped.")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            print("Monitoring failed:", error)

    print("CSV saved:", filename)