import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


n = int(sys.argv[1])
stop_file = Path(sys.argv[2])
ready_file = Path(sys.argv[3])

# Find this user's Ignition Gateway Java process.
matches = []

for process in psutil.process_iter(["cmdline", "uids"]):
    try:
        command = process.info["cmdline"] or []

        if (
            process.info["uids"].real == os.getuid()
            and "com.inductiveautomation.catapult.Catapult" in command
        ):
            matches.append(process)

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

if len(matches) != 1:
    raise SystemExit(
        f"Expected one Ignition JVM, found {len(matches)}"
    )

process = matches[0]
process.cpu_percent(None)

writer = csv.writer(sys.stdout)

if os.environ.get("WRITE_HEADER") == "1":
    writer.writerow([
        "time_utc",
        "N",
        "pid",
        "cpu_percent",
        "rss_mb",
    ])

sys.stdout.flush()
ready_file.touch()

try:
    while not stop_file.exists():
        time.sleep(1)

        if stop_file.exists():
            break

        cpu = process.cpu_percent(None)
        ram_mb = process.memory_info().rss / 1_000_000

        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            n,
            process.pid,
            cpu,
            round(ram_mb, 2),
        ])
        sys.stdout.flush()

except KeyboardInterrupt:
    pass

except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
    print(
        f"Ignition monitoring failed: {error}",
        file=sys.stderr,
    )
    sys.exit(1)