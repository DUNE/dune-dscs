# Set up the shell for the new-bridge stress test. Source it, don't run it:
#
#     source ~/dune-dscs/archive/stress_test/new_bridge/setup_env.sh
#
# It activates ~/DSCS/dscs-env (so plain `python` has dune_dscs), goes to
# archive/stress_test, checks the branch, and defines short commands:
#
#     fleet_start | fleet_stop | fleet_status   emulators on THIS host
#     check_fleet [--verbose]                   all 1000 emulators answer (from the bridge host)
#     bridge_diag --devices N ...               bridge_diagnostic.py
#     run_full                                  run_bridge_test.sh (pass env vars as usual)
#     plot_results [options]                    plot script, with ~/DSCS/opcua-env

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Source this file instead: source ${BASH_SOURCE[0]}" >&2
    exit 1
fi

STRESS_NEW_BRIDGE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STRESS_DIR="$(dirname -- "$STRESS_NEW_BRIDGE")"
DSCS_ENV="${DSCS_ENV:-$HOME/DSCS/dscs-env}"
PLOT_ENV="${PLOT_ENV:-$HOME/DSCS/opcua-env}"

# Leave any active venv (e.g. opcua-env), then activate dscs-env.
if [[ -n "${VIRTUAL_ENV:-}" ]] && declare -F deactivate > /dev/null; then
    deactivate
fi
if [[ ! -f "$DSCS_ENV/bin/activate" ]]; then
    echo "Missing $DSCS_ENV. Create it first (README section 0)." >&2
    return 1
fi
source "$DSCS_ENV/bin/activate"

cd -- "$STRESS_DIR" || return 1

branch="$(git -C "$STRESS_DIR" branch --show-current 2>/dev/null)"
if [[ "$branch" != "mainz-test-stand/develop" ]]; then
    echo "WARNING: branch is '$branch', expected mainz-test-stand/develop." >&2
fi
unset branch

if ! python -c "import dune_dscs.bridge, dune_dscs.emulator.wib" 2> /dev/null; then
    echo "WARNING: dune_dscs does not import in $DSCS_ENV. Run: $DSCS_ENV/bin/pip install -e ~/dune-dscs" >&2
fi

fleet_start()  { python "$STRESS_NEW_BRIDGE/emulator_fleet.py" start "$@"; }
fleet_stop()   { python "$STRESS_NEW_BRIDGE/emulator_fleet.py" stop "$@"; }
fleet_status() { python "$STRESS_NEW_BRIDGE/emulator_fleet.py" status "$@"; }
check_fleet()  { python "$STRESS_NEW_BRIDGE/check_fleet.py" "$@"; }
bridge_diag()  { python "$STRESS_NEW_BRIDGE/bridge_diagnostic.py" "$@"; }
run_full()     { "$STRESS_NEW_BRIDGE/run_bridge_test.sh" "$@"; }
plot_results() { "$PLOT_ENV/bin/python" "$STRESS_NEW_BRIDGE/plot_new_bridge_results.py" "$@"; }

echo "$(hostname -s): dscs-env active, in $PWD"
echo "Commands: fleet_start fleet_stop fleet_status check_fleet bridge_diag run_full plot_results"
