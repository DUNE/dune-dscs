import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300

emulators = []
for process in psutil.process_iter(["cmdline", "uids"]):
    try:
        if (
            process.info["uids"].real == os.getuid()
            and any(
                Path(arg).name == "zmq_emulator.py"
                for arg in process.info["cmdline"] or []
            )
        ):
            process.cpu_percent(None)
            emulators.append(process)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

writer = csv.writer(sys.stdout)
writer.writerow(["time_utc", "emulators", "cpu_percent", "rss_mb"])
sys.stdout.flush()

try:
    for _ in range(duration):
        time.sleep(1)
        cpu = ram = count = 0

        for process in emulators:
            try:
                process_cpu = process.cpu_percent(None)
                process_ram = process.memory_info().rss
                cpu += process_cpu
                ram += process_ram
                count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            count,
            round(cpu, 2),
            round(ram / 1_000_000, 2),
        ])
        sys.stdout.flush()
except KeyboardInterrupt:
    pass