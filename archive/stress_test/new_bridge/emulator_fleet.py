#!/usr/bin/env python3
"""Start, stop or check the dune_dscs WIB emulators on THIS host.

One emulator process per port (default 100 ports from 5555), bound to 0.0.0.0
so the bridge host can reach them. PIDs are recorded in
archive/stress_test/.runtime/dscs_<host>.jsonl; stop only kills processes whose PID,
start time and command line still match that record.

    python emulator_fleet.py start [--count 100] [--base-port 5555] [--timing FILE]
    python emulator_fleet.py stop
    python emulator_fleet.py status

Use fleet.sh to run this on every host listed in hosts.txt.
"""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # archive/stress_test/
RUNTIME = ROOT / ".runtime"
HOST = socket.gethostname().split(".")[0]
STATE = RUNTIME / f"dscs_{HOST}.jsonl"
LOGS = RUNTIME / "dscs_emulator_logs" / HOST


def start_time(pid):
    """Process start time in clock ticks (field 22 of /proc/<pid>/stat)."""
    try:
        return (Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split())[19]
    except (OSError, IndexError):
        return None


def command(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[:-1]
    except OSError:
        return None


def emulator_command(port, timing):
    cmd = [sys.executable, "-m", "dune_dscs.emulator", "wib",
           "--host", "0.0.0.0", "--port", str(port), "--vary"]
    if timing:
        cmd += ["--timing", str(Path(timing).resolve())]
    return cmd


def alive(record):
    pid = record["pid"]
    return (start_time(pid) == record["started"]
            and command(pid) == [part.encode() for part in record["cmd"]])


def read_records(state):
    state.seek(0)
    return [json.loads(line) for line in state if line.strip()]


def start(args):
    RUNTIME.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    ports = range(args.base_port, args.base_port + args.count)
    with STATE.open("a+") as state:
        fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(alive(r) for r in read_records(state)):
            raise SystemExit(f"{HOST}: emulators already recorded as running; run stop first.")
        state.seek(0)
        state.truncate()
        for port in ports:  # Check every port before starting anything.
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("0.0.0.0", port))
                except OSError:
                    raise SystemExit(f"{HOST}: port {port} is in use (old zmq_emulator fleet still running?).")
        children = []
        for port in ports:
            cmd = emulator_command(port, args.timing)
            with (LOGS / f"wib_{port}.log").open("w") as log:
                child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
            children.append(child)
            record = {"pid": child.pid, "started": start_time(child.pid), "port": port, "cmd": cmd}
            state.write(json.dumps(record) + "\n")
            state.flush()
        time.sleep(2)
        running = sum(child.poll() is None for child in children)
    if running != len(children):
        raise SystemExit(f"{HOST}: only {running}/{len(children)} emulators are running; "
                         f"see {LOGS}, then run stop.")
    print(f"{HOST}: {running} WIB emulators running on ports {ports.start}-{ports.stop - 1}.")


def stop(args):
    if not STATE.exists():
        print(f"{HOST}: no recorded emulators.")
        return
    with STATE.open("r+") as state:
        fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        records = [r for r in read_records(state) if alive(r)]
        for record in records:
            os.kill(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(alive(r) for r in records):
            time.sleep(0.2)
        remaining = [r for r in records if alive(r)]
        for record in remaining:
            os.kill(record["pid"], signal.SIGKILL)
        time.sleep(0.5)
        remaining = [r for r in remaining if alive(r)]
        state.seek(0)
        state.truncate()
        for record in remaining:
            state.write(json.dumps(record) + "\n")
    print(f"{HOST}: stopped {len(records) - len(remaining)} emulators.")
    if remaining:
        raise SystemExit(f"{HOST}: {len(remaining)} emulators could not be stopped.")


def status(args):
    records = []
    if STATE.exists():
        with STATE.open() as state:
            records = read_records(state)
    running = [r for r in records if alive(r)]
    ports = sorted(r["port"] for r in running)
    span = f" (ports {ports[0]}-{ports[-1]})" if ports else ""
    print(f"{HOST}: {len(running)}/{len(records)} recorded emulators running{span}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--count", type=int, default=100, help="emulators on this host (default 100)")
    parser.add_argument("--base-port", type=int, default=5555)
    parser.add_argument("--timing", help="optional emulator response-delay profile (examples/timing/*.json)")
    args = parser.parse_args()
    if not 1 <= args.count or not 1 <= args.base_port <= 65535 - args.count:
        parser.error("invalid --count/--base-port")
    try:
        {"start": start, "stop": stop, "status": status}[args.action](args)
    except BlockingIOError:
        raise SystemExit(f"{HOST}: another fleet command is running.")


if __name__ == "__main__":
    main()
