#!/bin/bash
cd "$(dirname "$0")" || exit 1

python="$HOME/DSCS/opcua-env/bin/python"
logdir="emulator_logs/$(hostname -s)"
mkdir -p "$logdir" || exit 1

# Check the exact Python environment used by the launcher.
if ! "$python" -c 'import zmq, zmq_em_pb2'; then
    echo "ERROR: Python dependencies failed on $(hostname -s)."
    exit 1
fi

start_emulator() {
    local port="$1"
    local script="$2"
    local logfile="$logdir/$port.log"

    if [ ! -f "$script" ]; then
        echo "ERROR: File not found: $script"
        return 1
    fi

    if ! "$python" -m py_compile "$script"; then
        echo "ERROR: Python syntax check failed: $script"
        return 1
    fi

    if ss -H -ltn "sport = :$port" | grep -q .; then
        echo "ERROR: Port $port is already in use — skipping."
        return 1
    fi

    EMULATOR_PORT="$port" nohup \
        "$python" -u "$script" \
        > "$logfile" 2>&1 < /dev/null &

    local pid=$!
    echo "$pid" > "$logdir/$port.pid"

    sleep 1

    if ! kill -0 "$pid" 2>/dev/null; then
        echo "ERROR: $script exited on port $port:"
        cat "$logfile"
        rm -f "$logdir/$port.pid"
        return 1
    fi

    echo "RUNNING: $(hostname -s), port $port, PID $pid"
    echo "Log: $logfile"
}

failed=0

for port in {5555..5654}; do #100 EMULATORS PER MACHINE 
    start_emulator "$port" zmq_emulator.py || failed=1
done

exit "$failed"
