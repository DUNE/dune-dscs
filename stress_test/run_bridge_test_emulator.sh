#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

CYCLES=300
MAX_DEVICES=1000
STEP=100

PYTHON="$HOME/DSCS/opcua-env/bin/python"
MONITOR="$PWD/monitor_emulators.py"

HOSTS=(
    "Weber03 134.93.131.35"
    "Weber06 134.93.128.228"
    "Weber07 134.93.128.229"
    "Weber02 134.93.130.214"
    "Weber09 134.93.128.243"
    "Weber10 134.93.129.24"
    "Weber11 134.93.129.16"
    "Weber12 134.93.131.161"
    "Weber13 134.93.129.22"
    "Weber14 134.93.129.26"
)

DEVICE_COUNTS=()
for ((n = 110; n <= MAX_DEVICES; n += STEP)); do
    DEVICE_COUNTS+=("$n")
done

# Refuse to overwrite existing results.
for n in "${DEVICE_COUNTS[@]}"; do
    if [[ -e "bridge_N${n}.csv" ]]; then
        echo "Existing file: bridge_N${n}.csv"
        exit 1
    fi

    for entry in "${HOSTS[@]}"; do
        read -r name ip <<< "$entry"
        if [[ -e "emulators_N${n}_${name}.csv" ||
              -e "emulators_N${n}_${name}.err" ]]; then
            echo "Existing emulator logs: N=${n}, ${name}"
            exit 1
        fi
    done
done

pids=()
names=()
stop_dir=""

stop_monitors() {
    if [[ -n "$stop_dir" ]]; then
        touch "$stop_dir/stop"

        for i in "${!pids[@]}"; do
            if ! wait "${pids[$i]}"; then
                echo "Monitor failed: ${names[$i]}; check its .err file." >&2
            fi
        done

        rm -f "$stop_dir/stop"
        rmdir "$stop_dir"
        stop_dir=""
        pids=()
        names=()
    fi
}

trap stop_monitors EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for n in "${DEVICE_COUNTS[@]}"; do
    echo
    echo "=== Testing ${n} devices, ${CYCLES} cycles ==="

    # Shared home directory: every machine sees this stop file.
    stop_dir=$(mktemp -d "$PWD/.emulator-monitor.XXXXXX")

    # Start emulator logging on all hosts in the background.
    for entry in "${HOSTS[@]}"; do
        read -r name ip <<< "$entry"

        ssh -o BatchMode=yes -o ConnectTimeout=10 \
            "lgoncalve@$ip" \
            "'$PYTHON' -u '$MONITOR' '$stop_dir/stop'" \
            > "emulators_N${n}_${name}.csv" \
            2> "emulators_N${n}_${name}.err" &

        pids+=("$!")
        names+=("$name")
    done

    # Run the bridge while the emulator monitors are running.
    "$PYTHON" ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES"

    # Signal the monitors to finish, then wait for them.
    stop_monitors

    echo "Saved bridge and emulator logs for N=${n}"
done

echo
echo "All tests completed."