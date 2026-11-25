#!/usr/bin/env bash
# Run emulator_fleet.py start|stop|status on every host in hosts.txt.
#
# usage: new_bridge/fleet.sh start|stop|status [extra emulator_fleet.py options]
#   e.g. new_bridge/fleet.sh start --count 100
#
# environment:
#   PYTHON       interpreter with dune_dscs installed (default ~/DSCS/dscs-env/bin/python)
#   REMOTE_USER  ssh user (default: current user)
#   HOSTS_FILE   host list (default: new_bridge/hosts.txt)
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$HOME/DSCS/dscs-env/bin/python}"
REMOTE_USER="${REMOTE_USER:-$(id -un)}"
HOSTS_FILE="${HOSTS_FILE:-$HERE/hosts.txt}"
local_host=$(hostname -s)

if [[ $# -lt 1 ]]; then
    echo "usage: $0 start|stop|status [options]" >&2
    exit 1
fi

failed=0
pids=()
while read -r name ip _; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    printf -v remote '%q ' "$PYTHON" "$HERE/emulator_fleet.py" "$@"
    if [[ "$local_host" == "etapweber${name#Weber}" ]]; then
        bash -c "$remote" &
    else
        ssh -n -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_USER@$ip" "$remote" &
    fi
    pids+=("$!")
done < "$HOSTS_FILE"

for pid in "${pids[@]}"; do
    wait "$pid" || failed=1
done
exit "$failed"
