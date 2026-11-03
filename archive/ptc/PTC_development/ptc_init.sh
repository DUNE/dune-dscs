#!/bin/sh

LOG=/var/log/ptc_startup.log

echo "PTC init start: $(date)" >> $LOG

# Optional: minimal delay
sleep 2

# Start server EARLY
echo "Starting ptc_server" >> $LOG
/bin/ptc_server >> /var/log/ptc_server.log 2>&1 &

# Optional: hardware setup AFTER start
# (only if needed)
# /etc/whatever/setup_commands

echo "PTC init complete" >> $LOG
