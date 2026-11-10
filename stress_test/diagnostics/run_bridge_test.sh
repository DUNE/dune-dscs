#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Select the device counts to test.
DEVICE_COUNTS=(110)

CYCLES="${CYCLES:-300}"
WARMUP="${WARMUP:-30}"  # Seconds.
RESULTS_DIR="${RESULTS_DIR:-$PWD/results/bridge_only}"
PYTHON="${PYTHON:-$HOME/DSCS/opcua-env/bin/python}"

mkdir -p -- "$RESULTS_DIR"

# Check all output paths before starting.
for n in "${DEVICE_COUNTS[@]}"; do
    if [[ -e "$RESULTS_DIR/bridge_N${n}.csv" ]]; then
        echo "Existing file: $RESULTS_DIR/bridge_N${n}.csv" >&2
        echo "Choose another RESULTS_DIR for a new experiment." >&2
        exit 1
    fi
done

for n in "${DEVICE_COUNTS[@]}"; do
    echo "Testing N=${n}: ${CYCLES} cycles, ${WARMUP} s warm-up."

    "$PYTHON" bridge/ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES" \
        --warmup "$WARMUP" \
        --output-dir "$RESULTS_DIR"

    echo "Saved $RESULTS_DIR/bridge_N${n}.csv"
done

echo "All tests completed."