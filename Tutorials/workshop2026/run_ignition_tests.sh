#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PYTHON="$HOME/DSCS/opcua-env/bin/python"
MONITOR="$PWD/monitor_ignition.py"

#DEVICE_COUNTS=(1 10 110 210 310 410 510 610 710 810 910 1000)
#DEVICE_COUNTS=(10 110 210 310 410 510 610 710 810 900)
DEVICE_COUNTS=(900)
CYCLES=300
WARMUP=30

monitor_pid=""
control_dir=""

cleanup() {
    if [[ -n "$control_dir" ]]; then
        touch "$control_dir/stop"
    fi

    if [[ -n "$monitor_pid" ]]; then
        if ! wait "$monitor_pid"; then
            echo "Ignition monitor failed; see terminal output." >&2
        fi
        monitor_pid=""
    fi

    if [[ -n "$control_dir" ]]; then
        rm -f "$control_dir/stop" "$control_dir/ready"
        rmdir "$control_dir"
        control_dir=""
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for n in "${DEVICE_COUNTS[@]}"; do

    # Check completion and clear results only for an unfinished N.
    action=$("$PYTHON" - "$n" "$CYCLES" <<'PY'
import csv
import os
import sys
import tempfile
from pathlib import Path

n = int(sys.argv[1])
expected_cycles = int(sys.argv[2])
bridge = Path(f"bridge_N{n}.csv")

complete = False

if bridge.exists():
    try:
        with bridge.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        complete = (
            len(rows) == expected_cycles
            and [int(row["cycle"]) for row in rows]
                == list(range(1, expected_cycles + 1))
            and all(int(row["devices"]) == n for row in rows)
            and all(None not in row for row in rows)
            and all(
                all(value is not None for value in row.values())
                for row in rows
            )
        )
    except (ValueError, KeyError, TypeError, csv.Error):
        complete = False

if complete:
    print("skip")
    sys.exit(0)

# Remove this N from the combined logs.
for filename in (
    "ignition_resources.csv",
    "ignition_tag_diagnostics.csv",
):
    path = Path(filename)

    if not path.exists() or path.stat().st_size == 0:
        continue

    temporary = None

    try:
        with path.open(newline="") as source:
            reader = csv.DictReader(source)
            fields = reader.fieldnames

            column = (
                "N" if fields and "N" in fields
                else "devices" if fields and "devices" in fields
                else None
            )

            if column is None:
                raise RuntimeError(
                    f"{filename}: missing N/devices column; "
                    "file was not changed"
                )

            with tempfile.NamedTemporaryFile(
                mode="w",
                newline="",
                dir=path.parent,
                delete=False,
            ) as destination:
                temporary = Path(destination.name)
                writer = csv.DictWriter(
                    destination, fieldnames=fields
                )
                writer.writeheader()

                for row in reader:
                    # Do not silently rewrite malformed CSVs.
                    if (
                        None in row
                        or any(value is None for value in row.values())
                    ):
                        raise RuntimeError(
                            f"{filename}: malformed row; "
                            "file was not changed"
                        )

                    if int(row[column]) != n:
                        writer.writerow(row)

        os.replace(temporary, path)
        temporary = None

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

bridge.unlink(missing_ok=True)
print("run")
PY
)

    if [[ "$action" == "skip" ]]; then
        echo "N=${n}: already completed; skipping."
        continue
    fi

    echo
    echo "=== Starting/restarting N=${n} ==="

    control_dir=$(mktemp -d "$PWD/.ignition-monitor.XXXXXX")

    if [[ -s ignition_resources.csv ]]; then
        export WRITE_HEADER=0
    else
        export WRITE_HEADER=1
    fi

    "$PYTHON" -u "$MONITOR" \
        "$n" "$control_dir/stop" "$control_dir/ready" \
        >> ignition_resources.csv &

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
        echo "Monitor did not become ready." >&2
        exit 1
    fi

    "$PYTHON" ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES" \
        --warmup "$WARMUP"

    touch "$control_dir/stop"

    if wait "$monitor_pid"; then
        monitor_pid=""
    else
        monitor_pid=""
        echo "Ignition monitor failed." >&2

        # Leave this N eligible for a restart.
        rm -f -- "bridge_N${n}.csv"
        exit 1
    fi

    cleanup

    echo "Completed N=${n}"
done

echo "All tests completed."