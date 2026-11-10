#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

exec "$HOME/DSCS/opcua-env/bin/python" - <<'PY'
import fcntl
import json
import os
import socket
from pathlib import Path

import psutil

base = Path.cwd()
script = str(base / "emulators" / "zmq_emulator.py")
host = socket.gethostname().split(".")[0]
state_file = base / ".runtime" / f"{host}.jsonl"

if not state_file.exists():
    raise SystemExit(f"{host}: no recorded emulators.")

with state_file.open("r+") as state:
    fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
    records = [json.loads(line) for line in state if line.strip()]

    pending = []
    retained = []

    for record in records:
        try:
            process = psutil.Process(record["pid"])

            # Verify identity before sending SIGTERM.
            if (
                process.uids().real != os.getuid()
                or abs(process.create_time() - record["started"]) > 0.001
                or process.cmdline()[1:] != ["-u", script]
            ):
                continue

            process.terminate()
            pending.append((process, record))

        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            retained.append(record)

    processes = [process for process, _ in pending]
    gone, alive = psutil.wait_procs(processes, timeout=10)

    retained.extend(
        record for process, record in pending if process in alive
    )

    # Keep records for processes that could not be stopped.
    state.seek(0)
    state.truncate()

    for record in retained:
        state.write(json.dumps(record) + "\n")

print(f"{host}: stopped {len(gone)} emulators.")

if retained:
    raise SystemExit(
        f"{host}: {len(retained)} processes remain unresolved; "
        "their runtime records were kept."
    )
PY