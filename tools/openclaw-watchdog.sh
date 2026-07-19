#!/usr/bin/env bash
# openclaw-watchdog.sh — restart the OpenClaw gateway if it's silently hung.
#
# A "silent hang" is when the process is alive but hasn't logged anything
# in N minutes (the Telegram polling loop died without crashing). systemd's
# Restart=on-failure only triggers on a crash, not a silent hang.
#
# Run via cron every 10 minutes:
#   */10 * * * * /home/Developer/game/tools/openclaw-watchdog.sh >> /tmp/openclaw-watchdog.log 2>&1

# cron doesn't inherit the D-Bus / XDG environment — set it explicitly
# so systemctl --user and journalctl --user work from cron.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

STALE_MINUTES=${STALE_MINUTES:-15}
JOURNAL_SINCE="${STALE_MINUTES} min ago"
LOG_PREFIX="[watchdog $(date -u +%H:%M)]"

# Check if the service is active at all
if ! systemctl --user is-active --quiet openclaw; then
    echo "$LOG_PREFIX openclaw not active — attempting restart"
    systemctl --user restart openclaw
    exit 0
fi

# Check if there are any journal entries in the last N minutes
ENTRIES=$(journalctl --user -u openclaw --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | wc -l)
if [ "$ENTRIES" -eq 0 ]; then
    echo "$LOG_PREFIX no logs in ${STALE_MINUTES}min — silent hang detected, restarting"
    systemctl --user restart openclaw
    sleep 3
    NEW_PID=$(systemctl --user show openclaw -p MainPID --value)
    echo "$LOG_PREFIX restarted, new PID=$NEW_PID"
else
    echo "$LOG_PREFIX ok ($ENTRIES entries in last ${STALE_MINUTES}min)"
fi
