#!/usr/bin/env bash
# openclaw-watchdog.sh — restart the OpenClaw gateway if it's silently hung.
#
# Detects three hang patterns:
# 1. "silent hang": no logs at all in N minutes (polling loop died)
# 2. "fetch-timeout storm": all recent logs are fetch-timeouts (proxy dead)
# 3. "agent stuck": inbound message received but no skill/helper/MEDIA activity
#    within N minutes (qwen3.6:35b context overflow or inference stuck)
#
# Run via cron every 5 minutes:
#   */5 * * * * /home/Developer/game/tools/openclaw-watchdog.sh >> /tmp/openclaw-watchdog.log 2>&1

# cron doesn't inherit the D-Bus / XDG environment — set it explicitly
# so systemctl --user and journalctl --user work from cron.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

STALE_MINUTES=${STALE_MINUTES:-10}
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
    exit 0
fi

# Also detect "fetch-timeout storm": the gateway is alive and logging, but ALL
# recent entries are fetch-timeout errors (the Telegram polling loop is stuck
# retrying a dead proxy connection). If every log line in the window is a
# fetch-timeout, the gateway is effectively hung — restart it.
TIMEOUT_ENTRIES=$(journalctl --user -u openclaw --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | grep -c "fetch-timeout")
if [ "$ENTRIES" -gt 0 ] && [ "$TIMEOUT_ENTRIES" -eq "$ENTRIES" ]; then
    echo "$LOG_PREFIX all $ENTRIES entries are fetch-timeouts — proxy-storm hang, restarting"
    systemctl --user restart openclaw
    sleep 3
    NEW_PID=$(systemctl --user show openclaw -p MainPID --value)
    echo "$LOG_PREFIX restarted, new PID=$NEW_PID"
    exit 0
fi

# Detect "agent stuck": an inbound message was received but no skill/helper/MEDIA
# activity followed within the window. This catches qwen3.6:35b context overflow
# or inference stuck states where the gateway is alive but the agent isn't making
# progress.
INBOUND_COUNT=$(journalctl --user -u openclaw --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | grep -c "Inbound message")
if [ "$INBOUND_COUNT" -gt 0 ]; then
    SKILL_ACTIVITY=$(journalctl --user -u openclaw --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | grep -c -i "styleforge\|run_helper\|helper\|MEDIA:\|skill.*invoke\|POST.*api/runs\|assembler.done")
    if [ "$SKILL_ACTIVITY" -eq 0 ]; then
        echo "$LOG_PREFIX inbound message(s)=$INBOUND_COUNT but no skill activity=$SKILL_ACTIVITY in ${STALE_MINUTES}min — agent stuck, restarting"
        # Clean up stale sessions before restart to prevent context buildup
        SESS_DIR="/home/Developer/build_a_claw_workshop-bundle/openclaw-home/.openclaw/agents/main/sessions"
        if [ -d "$SESS_DIR" ]; then
            find "$SESS_DIR" -name "*.jsonl" -mmin +${STALE_MINUTES} -delete 2>/dev/null
            find "$SESS_DIR" -name "*.trajectory.jsonl" -mmin +${STALE_MINUTES} -delete 2>/dev/null
            echo '{}' > "$SESS_DIR/sessions.json" 2>/dev/null
        fi
        systemctl --user restart openclaw
        sleep 3
        NEW_PID=$(systemctl --user show openclaw -p MainPID --value)
        echo "$LOG_PREFIX restarted, new PID=$NEW_PID (sessions cleaned)"
        exit 0
    fi
fi

echo "$LOG_PREFIX ok ($ENTRIES entries, $TIMEOUT_ENTRIES timeouts, $INBOUND_COUNT inbound)"
