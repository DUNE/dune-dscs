#!/usr/bin/env bash
set -euo pipefail

PTC_IP="${1:?Usage: ./deploy.sh <PTC_IP> [install_dir]}"
INSTALL_DIR="${2:-/usr/local/bin}"

echo "=== Building on $(hostname) ==="
./build.sh

echo "=== Copying binaries to PTC (${PTC_IP}) ==="
scp ./ptc_server ./peek "root@${PTC_IP}:/tmp/"

echo "=== Installing to ${INSTALL_DIR} on PTC ==="
ssh "root@${PTC_IP}" bash -lc "'
  set -euo pipefail

  mkdir -p \"${INSTALL_DIR}\"
  cp /tmp/ptc_server \"${INSTALL_DIR}/ptc_server\"
  cp /tmp/peek       \"${INSTALL_DIR}/peek\"
  chmod +x \"${INSTALL_DIR}/ptc_server\" \"${INSTALL_DIR}/peek\"

  # Optional: if ptc_server is already running, restart it
  if pidof ptc_server >/dev/null 2>&1; then
    echo \"ptc_server running -> restarting\"
    killall ptc_server || true
    sleep 0.2
  fi

  # Start server in background (optional). Comment out if you prefer ptc_init.sh to manage it.
  nohup \"${INSTALL_DIR}/ptc_server\" >/var/log/ptc_server.log 2>&1 &

  echo \"Installed: ${INSTALL_DIR}/ptc_server and ${INSTALL_DIR}/peek\"
  echo \"ptc_server log: /var/log/ptc_server.log\"
'"
echo "=== Done ==="