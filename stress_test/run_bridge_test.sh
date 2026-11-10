#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

CYCLES=300
MAX_DEVICES=1200
STEP=100

DEVICE_COUNTS=(110)
#for ((n = 110; n <= MAX_DEVICES; n += STEP)); do
 #   DEVICE_COUNTS+=("$n")
#done

# Check before starting: the bridge opens CSV files without overwriting.
for n in "${DEVICE_COUNTS[@]}"; do
    if [[ -e "bridge_N${n}.csv" ]]; then
        echo "Existing file: bridge_N${n}.csv"
        echo "Move previous results before starting."
        exit 1
    fi
done

for n in "${DEVICE_COUNTS[@]}"; do
    echo
    echo "=== Testing ${n} devices, ${CYCLES} cycles ==="

    python ignition_pybridge_diagnostic.py \
        --devices "$n" \
        --cycles "$CYCLES"

    echo "Saved bridge_N${n}.csv"
done

echo
echo "All tests completed."