#!/usr/bin/env bash
# Start one emulator per port, all in the background; Ctrl-C stops them all.
#
# usage: examples/scripts/start_emulator.sh [FIRST_PORT] [LAST_PORT]
#   default: WIBs on ports 1234-1243
#
# environment:
#   KIND=wib|daphne|pdu  device type (default wib)
#   HOST=127.0.0.1       bind address; 0.0.0.0 to accept other machines
#   LOGDIR=logs          one log per emulator: $LOGDIR/<kind>_<port>.log
#   EXTRA="--vary"       extra emulator options, e.g. "--vary --vary-period 30"
#
# examples:
#   examples/scripts/start_emulator.sh 1234 1263
#   HOST=0.0.0.0 EXTRA="--vary" examples/scripts/start_emulator.sh 1234 1263
#   KIND=daphne examples/scripts/start_emulator.sh 40001 40005

set -u

KIND=${KIND:-wib}
FIRST=${1:-1234}
LAST=${2:-$FIRST}
[ $# -eq 0 ] && LAST=1243
HOST=${HOST:-127.0.0.1}
LOGDIR=${LOGDIR:-logs}
EXTRA=${EXTRA:-}

case "$KIND" in wib|daphne|pdu) ;; *) echo "KIND must be wib, daphne or pdu" >&2; exit 1 ;; esac
if [ "$FIRST" -gt "$LAST" ]; then echo "FIRST_PORT must be <= LAST_PORT" >&2; exit 1; fi

# Run from the repository root so uv finds the project, wherever we are called from.
cd "$(dirname "$0")/../.." || exit 1
mkdir -p "$LOGDIR"

# Sync once, then call the venv's python directly: much faster than
# `uv run` per emulator when starting many of them.
uv sync -q || exit 1
PYTHON=.venv/bin/python

pids=()
cleanup() {
    trap - INT TERM EXIT
    echo "stopping ${#pids[@]} $KIND emulators"
    kill "${pids[@]}" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup INT TERM EXIT

for ((p = FIRST; p <= LAST; p++)); do
    # shellcheck disable=SC2086  # EXTRA is meant to split into options
    "$PYTHON" -m dune_dscs.emulator "$KIND" --host "$HOST" --port "$p" $EXTRA \
        > "$LOGDIR/${KIND}_$p.log" 2>&1 &
    pids+=($!)
done

echo "started ${#pids[@]} $KIND emulators on $HOST:$FIRST-$LAST (logs in $LOGDIR/), Ctrl-C to stop"
wait
