#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Set these options here or provide their values as environment variables.
PYTHON="${PYTHON:-$HOME/DSCS/opcua-env/bin/python}"
DEVICE_COUNTS=(10 110 210 310 410 510 610 710 810 910 1000)
CYCLES="${CYCLES:-300}"
WARMUP="${WARMUP:-30}"  # Seconds.
TIMER_ENABLED="${TIMER_ENABLED:-true}"
CACHE_ENABLED="${CACHE_ENABLED:-true}"

for value in "$TIMER_ENABLED" "$CACHE_ENABLED" "${ENDURANCE:-false}"; do
    if [[ "$value" != "true" && "$value" != "false" ]]; then
        echo "TIMER_ENABLED, CACHE_ENABLED and ENDURANCE must be true or false." >&2
        exit 1
    fi
done

if [[ "$TIMER_ENABLED" == "false" ]]; then
    CASE_NAME="diagnostics_disabled"
    CACHE_ENABLED=false  # Caching has no recurring work to optimise here.
elif [[ "$CACHE_ENABLED" == "true" ]]; then
    CASE_NAME="timer_cached"
else
    CASE_NAME="timer_uncached"
fi

if [[ "${ENDURANCE:-false}" == "true" ]]; then
    CASE_NAME="endurance_$CASE_NAME"
fi
RESULTS_DIR="${RESULTS_DIR:-$PWD/results/$CASE_NAME}"

MONITOR="$PWD/diagnostics/monitor_ignition.py"
mkdir -p -- "$RESULTS_DIR" "$PWD/.runtime"

# Prevent two runners from modifying the same measurements concurrently.
exec 9> "$PWD/.runtime/ignition_tests.lock"
if ! "$PYTHON" - <<'LOCK'
import fcntl

try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit(1)
LOCK
then
    echo "Another Ignition test runner is already active." >&2
    exit 1
fi

# An endurance run is a fresh experiment: never resume or delete its evidence.
if [[ "${ENDURANCE:-false}" == "true" ]]; then
    "$PYTHON" - "$PYTHON" "$PWD" "$RESULTS_DIR" \
        "${DEVICE_COUNT:-1000}" "$WARMUP" "$TIMER_ENABLED" \
        "$CACHE_ENABLED" "${POST_FAILURE_SECONDS:-60}" <<'ENDURANCE'
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

python, root, folder, number, warmup, timer, cache, post = sys.argv[1:]
root, folder = Path(root), Path(folder).resolve()
number, warmup, post = int(number), float(warmup), float(post)
if not 1 <= number <= 1000:
    raise SystemExit("DEVICE_COUNT must be between 1 and 1000.")
if any(not math.isfinite(value) or value < 0 for value in (warmup, post)):
    raise SystemExit("WARMUP and POST_FAILURE_SECONDS must be nonnegative.")
if any(folder.glob("*.csv")) or any(folder.glob("*.log")):
    raise SystemExit(
        "Choose a fresh RESULTS_DIR; endurance data is preserved."
    )
settings = {
    "mode": "endurance", "device_counts": [number], "cycles": 0,
    "warmup_seconds": warmup, "timer_enabled": timer == "true",
    "cache_enabled": cache == "true", "post_failure_seconds": post,
    "automatic_restart": False,
}
settings_file = folder / "test_settings.json"
if settings_file.exists():
    raise SystemExit("Choose a new RESULTS_DIR for this endurance attempt.")
settings_file.write_text(json.dumps(settings, indent=2) + "\n")


def interrupted(signum, frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, interrupted)
started = time.monotonic()
monitor = bridge = None
status = 1
with (folder / "experiment.log").open("x", buffering=1) as log:
    def event(message):
        elapsed = time.monotonic() - started
        line = "%s | %.1f s | %s" % (
            datetime.now(timezone.utc).isoformat(), elapsed, message,
        )
        print(line, flush=True)
        print(line, file=log, flush=True)

    def stop(process):
        if process is None or process.poll() is not None:
            return
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            event("Process %d did not stop; sending SIGTERM" % process.pid)
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                event("Process %d did not stop; sending SIGKILL" % process.pid)
                process.kill()
                process.wait()

    with tempfile.TemporaryDirectory(
        dir=root / ".runtime", prefix="endurance-monitor.",
    ) as temporary, (folder / "ignition_resources.csv").open("x") as resources:
        control = Path(temporary)
        try:
            env = dict(os.environ, WRITE_HEADER="1", PYTHONUNBUFFERED="1")
            event("Starting endurance test: N=%d, controller PID=%d"
                  % (number, os.getpid()))
            monitor = subprocess.Popen([
                python, "-u", str(root / "diagnostics/monitor_ignition.py"),
                str(number), str(control / "stop"), str(control / "ready"),
            ], stdout=resources, stderr=log, env=env)
            deadline = time.monotonic() + 30
            while not (control / "ready").exists():
                if monitor.poll() is not None:
                    raise RuntimeError(
                        "Ignition resource monitor failed at startup"
                    )
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Ignition monitor was not ready within 30 s"
                    )
                time.sleep(0.2)
            bridge = subprocess.Popen([
                python, "-u",
                str(root / "bridge/ignition_pybridge_diagnostic.py"),
                "--devices", str(number), "--cycles", "0",
                "--warmup", str(warmup), "--output-dir", str(folder),
                "--timer-enabled", timer, "--cache-enabled", cache,
                "--wait-for-ignition",
            ], stdout=log, stderr=subprocess.STDOUT, env=env)
            event("Bridge PID=%d; output is in experiment.log" % bridge.pid)
            while bridge.poll() is None:
                if monitor.poll() is not None:
                    raise RuntimeError(
                        "Ignition monitor exited with code %s; stopping test"
                        % monitor.returncode
                    )
                time.sleep(0.5)
            event("Bridge exited with code %s" % bridge.returncode)
            status = bridge.returncode if bridge.returncode > 0 else 1
            event("Keeping Ignition resource monitoring for %.1f s" % post)
            deadline = time.monotonic() + post
            while time.monotonic() < deadline:
                if monitor.poll() is not None:
                    event(
                        "Ignition monitor also exited: %s" % monitor.returncode
                    )
                    break
                time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            event("Manual stop requested")
            status = 130
        except Exception as error:
            event("Test failed: %s" % error)
            traceback.print_exc(file=log)
            status = 1
        finally:
            stop(bridge)
            (control / "stop").touch()
            if monitor is not None:
                try:
                    monitor.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    stop(monitor)
            event(
                "Stopped; all CSVs and error output preserved; exit=%d"
                % status
            )
raise SystemExit(status)
ENDURANCE
    exit $?
fi

# Preserve the settings with the experiment and reject mixed configurations.
"$PYTHON" - "$RESULTS_DIR" "$CYCLES" "$WARMUP" \
    "$TIMER_ENABLED" "$CACHE_ENABLED" "${DEVICE_COUNTS[@]}" <<'SETTINGS'
import json
import math
import os
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
cycles = int(sys.argv[2])
warmup = float(sys.argv[3])
devices = [int(value) for value in sys.argv[6:]]

if cycles < 1 or not math.isfinite(warmup) or warmup < 0:
    raise SystemExit("Require cycles >= 1 and finite warm-up >= 0.")
if not devices or len(devices) != len(set(devices)):
    raise SystemExit("Supply a nonempty list of unique device counts.")
if any(not 1 <= number <= 1100 for number in devices):
    raise SystemExit("Device counts must be between 1 and 1000.")

settings = {
    "cycles": cycles,
    "warmup_seconds": warmup,
    "device_counts": devices,
    "timer_enabled": sys.argv[4] == "true",
    "cache_enabled": sys.argv[5] == "true",
    "gateway_timer_remains_enabled": True,
    "wait_for_good_tags": True,
    "resource_window": "setup, warm-up and measured cycles",
}
path = folder / "test_settings.json"

if path.exists():
    if json.loads(path.read_text()) != settings:
        raise SystemExit(
            "This results folder belongs to different settings. "
            "Choose another RESULTS_DIR."
        )
else:
    if any(folder.glob("*.csv")):
        raise SystemExit(
            "This folder has measurements without test_settings.json. "
            "Choose a new RESULTS_DIR."
        )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n")
    os.replace(temporary, path)
SETTINGS

printf 'Case: %s | Results: %s\n' "$CASE_NAME" "$RESULTS_DIR"

monitor_pid=""
control_dir=""
current_bridge=""

cleanup() {
    local failed=0

    if [[ -n "$control_dir" ]]; then
        touch "$control_dir/stop"
    fi

    if [[ -n "$monitor_pid" ]]; then
        if ! wait "$monitor_pid"; then
            echo "Ignition monitor failed; see terminal output." >&2
            failed=1
        fi
        monitor_pid=""
    fi

    if [[ -n "$control_dir" ]]; then
        rm -f -- "$control_dir/stop" "$control_dir/ready"
        rmdir -- "$control_dir"
        control_dir=""
    fi

    return "$failed"
}

on_exit() {
    local status=$?
    trap - EXIT

    if ! cleanup; then
        status=1
    fi

    # A bridge CSV alone must not mark a failed test as complete.
    if [[ -n "$current_bridge" ]]; then
        rm -f -- "$current_bridge"
    fi

    exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

check_run() {
    "$PYTHON" - "$1" "$CYCLES" "$RESULTS_DIR" "$2" \
        "$TIMER_ENABLED" <<'PY'
import csv
import math
import os
import sys
import tempfile
from pathlib import Path

number = int(sys.argv[1])
expected_cycles = int(sys.argv[2])
results_dir = Path(sys.argv[3])
operation = sys.argv[4]
timer_enabled = sys.argv[5] == "true"
bridge = results_dir / f"bridge_N{number}.csv"
resources = results_dir / "ignition_resources.csv"


def bridge_complete():
    """Check that every expected measured cycle was written."""
    if not bridge.is_file():
        return False

    try:
        with bridge.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        return (
            len(rows) == expected_cycles
            and [int(row["cycle"]) for row in rows]
            == list(range(1, expected_cycles + 1))
            and all(int(row["devices"]) == number for row in rows)
            and all(None not in row for row in rows)
            and all(
                all(value is not None for value in row.values())
                for row in rows
            )
        )
    except (ValueError, KeyError, TypeError, csv.Error):
        return False


def resource_samples_exist():
    """Require an Ignition resource sample for this device count."""
    if not resources.is_file():
        return False

    try:
        with resources.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if int(row["N"]) != number:
                    continue

                cpu = float(row["cpu_percent"])
                ram = float(row["rss_mb"])
                if (
                    math.isfinite(cpu) and cpu >= 0
                    and math.isfinite(ram) and ram >= 0
                ):
                    return True
    except (ValueError, KeyError, TypeError, csv.Error):
        return False

    return False


def diagnostic_samples_exist(filename):
    """Require Gateway output when diagnostic collection is enabled."""
    path = results_dir / filename
    if not path.is_file():
        return False
    try:
        with path.open(newline="") as handle:
            return any(
                int(row["N"]) == number for row in csv.DictReader(handle)
            )
    except (ValueError, KeyError, TypeError, csv.Error):
        return False


complete = bridge_complete() and resource_samples_exist()
if timer_enabled:
    complete = (
        complete
        and diagnostic_samples_exist("ignition_tag_diagnostics.csv")
        and diagnostic_samples_exist("ignition_timer_profile.csv")
    )

if operation == "verify":
    if not complete:
        raise SystemExit(f"N={number}: test output is incomplete.")
    raise SystemExit(0)

if complete:
    print("skip")
    raise SystemExit(0)

# Validate and prepare every replacement before changing existing CSVs.
replacements = []

try:
    for filename in (
        "ignition_resources.csv",
        "ignition_tag_diagnostics.csv",
        "ignition_timer_profile.csv",
    ):
        path = results_dir / filename
        if not path.exists() or path.stat().st_size == 0:
            continue

        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            rows = list(reader)

        column = (
            "N" if fields and "N" in fields
            else "devices" if fields and "devices" in fields
            else None
        )
        if column is None:
            raise RuntimeError(f"{path}: missing N/devices column.")

        retained = []
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise RuntimeError(f"{path}: malformed CSV row.")
            if int(row[column]) != number:
                retained.append(row)

        with tempfile.NamedTemporaryFile(
            mode="w", newline="", dir=results_dir, delete=False,
        ) as handle:
            temporary = Path(handle.name)
            replacements.append((temporary, path))
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(retained)

    # Remove the completion candidate before replacing associated samples.
    bridge.unlink(missing_ok=True)
    for temporary, path in replacements:
        os.replace(temporary, path)
finally:
    for temporary, _ in replacements:
        temporary.unlink(missing_ok=True)

print("run")
PY
}

for n in "${DEVICE_COUNTS[@]}"; do
    action=$(check_run "$n" prepare)

    if [[ "$action" == "skip" ]]; then
        echo "N=${n}: already completed; skipping."
        continue
    fi

    echo "Starting N=${n}: ${CYCLES} cycles, ${WARMUP} s warm-up."
    current_bridge="$RESULTS_DIR/bridge_N${n}.csv"
    control_dir=$(mktemp -d "$PWD/.runtime/ignition-monitor.XXXXXX")

    if [[ -s "$RESULTS_DIR/ignition_resources.csv" ]]; then
        export WRITE_HEADER=0
    else
        export WRITE_HEADER=1
    fi

    "$PYTHON" -u "$MONITOR" \
        "$n" "$control_dir/stop" "$control_dir/ready" \
        >> "$RESULTS_DIR/ignition_resources.csv" &
    monitor_pid=$!

    for ((i = 0; i < 30; i++)); do
        if ! kill -0 "$monitor_pid" 2>/dev/null; then
            echo "Monitor startup failed." >&2
            exit 1
        fi
        if [[ -f "$control_dir/ready" ]]; then
            break
        fi
        sleep 1
    done

    if [[ ! -f "$control_dir/ready" ]]; then
        echo "Monitor did not become ready within 30 seconds." >&2
        exit 1
    fi

    "$PYTHON" bridge/ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES" \
        --warmup "$WARMUP" \
        --output-dir "$RESULTS_DIR" \
        --timer-enabled "$TIMER_ENABLED" \
        --cache-enabled "$CACHE_ENABLED" \
        --wait-for-ignition

    cleanup
    check_run "$n" verify
    current_bridge=""
    echo "Completed N=${n}"
done

echo "All tests completed. Results: $RESULTS_DIR"
