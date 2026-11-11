#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Edit the device counts here. Other settings can also use environment variables.
DEVICE_COUNTS=(10 110 210 310 410 510 610 710 810 900)
CYCLES="${CYCLES:-300}"
WARMUP="${WARMUP:-30}"  # Seconds.
RESULTS_DIR="${RESULTS_DIR:-$PWD/results/emulator_bridge}"
PYTHON="${PYTHON:-$HOME/DSCS/opcua-env/bin/python}"
REMOTE_USER="${REMOTE_USER:-$(id -un)}"
MONITOR="$PWD/diagnostics/monitor_emulators.py"

# Match the hosts used by the diagnostic bridge.
HOSTS=(
    "Weber02 134.93.130.214"
    "Weber03 134.93.131.35"
    "Weber06 134.93.128.228"
    "Weber07 134.93.128.229"
    "Weber08 134.93.128.234"
    "Weber09 134.93.128.243"
    "Weber10 134.93.129.24"
    "Weber11 134.93.129.16"
    "Weber12 134.93.131.161"
    "Weber13 134.93.129.22"
    "Weber14 134.93.129.26"
)

mkdir -p -- "$RESULTS_DIR" "$PWD/.runtime"
pids=()
names=()
outputs=()
stop_dir=""
local_host=$(hostname -s)

# Check all output paths before starting any monitors.
for n in "${DEVICE_COUNTS[@]}"; do
    if [[ -e "$RESULTS_DIR/bridge_N${n}.csv" ]]; then
        echo "Existing file: $RESULTS_DIR/bridge_N${n}.csv" >&2
        exit 1
    fi

    for entry in "${HOSTS[@]}"; do
        read -r name ip <<< "$entry"
        output="$RESULTS_DIR/emulators_N${n}_${name}.csv"
        if [[ -e "$output" ]]; then
            echo "Existing file: $output" >&2
            exit 1
        fi
    done
done

stop_monitors() {
    local failed=0

    if [[ -z "$stop_dir" ]]; then
        return 0
    fi

    touch "$stop_dir/stop"

    for i in "${!pids[@]}"; do
        if ! wait "${pids[$i]}"; then
            echo "Monitor failed on ${names[$i]}; see terminal output." >&2
            failed=1
        fi
    done

    if [[ "$failed" == 0 ]]; then
        rm -f -- "$stop_dir/stop"
        rmdir -- "$stop_dir"
    else
        # A disconnected remote monitor may still need to see the stop marker.
        echo "Stop marker retained: $stop_dir/stop" >&2
    fi

    stop_dir=""
    pids=()
    names=()
    outputs=()
    return "$failed"
}

on_exit() {
    local status=$?
    trap - EXIT

    if ! stop_monitors; then
        status=1
    fi

    exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

have_samples() {
    "$PYTHON" - "$@" <<'PY'
import csv
import sys

for filename in sys.argv[1:]:
    try:
        with open(filename, newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            sample = next(reader, None)
    except (OSError, csv.Error):
        raise SystemExit(1)
    if not header or not sample or len(sample) != len(header):
        raise SystemExit(1)
PY
}

check_bridge() {
    "$PYTHON" - "$RESULTS_DIR/bridge_N${1}.csv" "$1" "$CYCLES" <<'CHECK'
import csv
import sys

filename, number, cycles = sys.argv[1:]
with open(filename, newline="") as handle:
    rows = list(csv.DictReader(handle))

complete = (
    len(rows) == int(cycles)
    and [int(row["cycle"]) for row in rows]
    == list(range(1, int(cycles) + 1))
    and all(int(row["devices"]) == int(number) for row in rows)
)
if not complete:
    raise SystemExit(f"N={number}: bridge output is incomplete.")
CHECK
}

for n in "${DEVICE_COUNTS[@]}"; do
    echo "Testing N=${n}: ${CYCLES} cycles, ${WARMUP} s warm-up."
    stop_dir=$(mktemp -d "$PWD/.runtime/emulator-monitor.XXXXXX")

    for entry in "${HOSTS[@]}"; do
        read -r name ip <<< "$entry"
        output="$RESULTS_DIR/emulators_N${n}_${name}.csv"

        if [[ "$local_host" == "etapweber${name#Weber}" ]]; then
            "$PYTHON" -u "$MONITOR" "$stop_dir/stop" > "$output" &
        else
            printf -v remote_command '%q ' \
                "$PYTHON" -u "$MONITOR" "$stop_dir/stop"
            ssh -n -o BatchMode=yes -o ConnectTimeout=10 \
                -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
                "$REMOTE_USER@$ip" "$remote_command" > "$output" &
        fi

        pids+=("$!")
        names+=("$name")
        outputs+=("$output")
    done

    ready=false
    for ((attempt = 0; attempt < 30; attempt++)); do
        for i in "${!pids[@]}"; do
            if ! kill -0 "${pids[$i]}" 2>/dev/null; then
                echo "Monitor startup failed on ${names[$i]}." >&2
                exit 1
            fi
        done

        if have_samples "${outputs[@]}"; then
            ready=true
            break
        fi
        sleep 1
    done

    if [[ "$ready" != true ]]; then
        echo "Not all emulator monitors produced samples within 30 s." >&2
        exit 1
    fi

    "$PYTHON" bridge/ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES" \
        --warmup "$WARMUP" \
        --output-dir "$RESULTS_DIR"

    stop_monitors
    check_bridge "$n"
    echo "Completed N=${n}"
done

echo "All tests completed. Results: $RESULTS_DIR"
