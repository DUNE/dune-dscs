#!/bin/bash
cd "$(dirname "$0")" || exit 1

logdir="emulator_logs/$(hostname -s)"

for file in "$logdir"/*.pid; do
    [ -f "$file" ] || continue
    pid=$(cat "$file")

    if kill -0 "$pid" 2>/dev/null &&
       ps -p "$pid" -o args= | grep -q 'zmq_emulator.py'; then
        kill -TERM "$pid"
        echo "$(hostname -s): stopped PID $pid"
    fi

    rm -f "$file"
done