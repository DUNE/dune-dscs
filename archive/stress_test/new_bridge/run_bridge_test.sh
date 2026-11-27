#!/usr/bin/env bash
# Emulator-increasing test with the new dune_dscs bridge (new-bridge version of
# diagnostics/run_bridge_test.sh). Start the fleet first: new_bridge/fleet.sh start
#
# Override with environment variables, e.g.
#   DEVICE_COUNTS="10 110 210" WINDOWS=30 RESULTS_DIR=results/try1 new_bridge/run_bridge_test.sh
#
#   DEVICE_COUNTS  N values (default 10 110 ... 910 1000)
#   WINDOWS        measured windows per N (default 300 = 300 polls per device, like the old
#                  300 cycles; 25 min per N at the 5 s period, about 4 h 45 min in total)
#   WARMUP         warm-up seconds per N (default 30)
#   PERIOD, TIMEOUT, CONCURRENCY   optional overrides of bridge-varying.yaml (5 s, 10 s, 32)
#   RESULTS_DIR    output folder (default results/new_bridge_scaling)
#   PYTHON         interpreter with dune_dscs installed (default ~/DSCS/dscs-env/bin/python)
#   HOSTS_FILE, PER_HOST, BASE_PORT   optional fleet overrides
#   STRESS_ENDPOINT (or ENDPOINT)  OPC UA endpoint of the bridge (default opc.tcp://127.0.0.1:4841/dune/)
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$HERE/.."

read -r -a DEVICE_COUNTS <<< "${DEVICE_COUNTS:-10 110 210 310 410 510 610 710 810 910 1000}"
WINDOWS="${WINDOWS:-300}"
WARMUP="${WARMUP:-30}"
RESULTS_DIR="${RESULTS_DIR:-$PWD/results/new_bridge_scaling}"
PYTHON="${PYTHON:-$HOME/DSCS/dscs-env/bin/python}"

extra=()
[[ -n "${PERIOD:-}" ]] && extra+=(--period "$PERIOD")
[[ -n "${TIMEOUT:-}" ]] && extra+=(--timeout "$TIMEOUT")
[[ -n "${CONCURRENCY:-}" ]] && extra+=(--concurrency "$CONCURRENCY")
[[ -n "${HOSTS_FILE:-}" ]] && extra+=(--hosts "$HOSTS_FILE")
[[ -n "${PER_HOST:-}" ]] && extra+=(--per-host "$PER_HOST")
[[ -n "${BASE_PORT:-}" ]] && extra+=(--base-port "$BASE_PORT")
[[ -n "${ENDPOINT:-}" ]] && extra+=(--endpoint "$ENDPOINT")

mkdir -p -- "$RESULTS_DIR"

# Check every output path before starting the sequence.
for n in "${DEVICE_COUNTS[@]}"; do
    if [[ -e "$RESULTS_DIR/bridge_N${n}.csv" ]]; then
        echo "Existing file: $RESULTS_DIR/bridge_N${n}.csv" >&2
        echo "Choose another RESULTS_DIR for a new experiment." >&2
        exit 1
    fi
done

echo "Emulator fleet:"
"$HERE/fleet.sh" status || true

for n in "${DEVICE_COUNTS[@]}"; do
    echo "Testing N=${n}: ${WINDOWS} windows, ${WARMUP} s warm-up."
    # pipefail: the condition fails when the diagnostic fails, not only tee.
    if ! "$PYTHON" -u "$HERE/bridge_diagnostic.py" \
        --devices "$n" \
        --windows "$WINDOWS" \
        --warmup "$WARMUP" \
        --output-dir "$RESULTS_DIR" \
        --require-all \
        "${extra[@]}" 2>&1 | tee "$RESULTS_DIR/bridge_N${n}.log"; then
        echo "N=${n} failed; see $RESULTS_DIR/bridge_N${n}.log" >&2
        exit 1
    fi
done

echo "All tests completed. Plot with:"
echo "  ~/DSCS/opcua-env/bin/python new_bridge/plot_new_bridge_results.py --data-dir $RESULTS_DIR"
