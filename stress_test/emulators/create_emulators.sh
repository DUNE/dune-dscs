#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

exec "$HOME/DSCS/opcua-env/bin/python" - <<'PY'
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

base = Path.cwd()
script = base / "emulators" / "zmq_emulator.py"
host = socket.gethostname().split(".")[0]

runtime = base / ".runtime"
runtime.mkdir(exist_ok=True)
state_file = runtime / f"{host}.jsonl"

compile(script.read_text(), str(script), "exec")

with state_file.open("a+") as state:
    # Prevent two launchers from starting the same fleet simultaneously.
    fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state.seek(0)

    if state.read().strip():
        raise SystemExit(
            f"{host}: run stop_emulators.sh before starting again."
        )

    # Check all ports before starting.
    for port in range(5555, 5655):
        with socket.socket() as connection:
            try:
                connection.bind(("0.0.0.0", port))
            except OSError:
                raise SystemExit(f"{host}: port {port} is unavailable.")

    children = []

    for port in range(5555, 5655):
        environment = os.environ.copy()
        environment["EMULATOR_PORT"] = str(port)

        child = subprocess.Popen(
            [sys.executable, "-u", str(script)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        children.append(child)

        record = {
            "pid": child.pid,
            "started": psutil.Process(child.pid).create_time(),
            "port": port,
        }
        state.write(json.dumps(record) + "\n")
        state.flush()

    time.sleep(1)
    running = sum(child.poll() is None for child in children)

    if running != len(children):
        raise SystemExit(
            f"{host}: only {running}/100 emulators remain running. "
            "Run stop_emulators.sh before retrying."
        )

print(f"{host}: 100 emulators running on ports 5555–5654.")
PY