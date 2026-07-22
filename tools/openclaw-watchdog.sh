#!/usr/bin/env bash
# openclaw-watchdog.sh — restart the OpenClaw gateway if it's silently hung.
#
# Detects three hang patterns:
# 1. "silent hang": no logs at all in N minutes (polling loop died)
# 2. "fetch-timeout storm": all recent logs are fetch-timeouts (proxy dead)
# 3. "agent stuck": inbound message received but no skill/helper/MEDIA activity
#    within N minutes (qwen3.6:35b context overflow or inference stuck)
#
# IMPORTANT: OpenClaw writes logs to BOTH journald AND its own log file
# (/tmp/openclaw/openclaw-YYYY-MM-DD.log). Some entries (like "Inbound message")
# only appear in the log file, not journald. This watchdog checks BOTH sources.
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

# OpenClaw's own log file (in addition to journald)
OC_LOG_DIR="/tmp/openclaw"
OC_LOG_TODAY="${OC_LOG_DIR}/openclaw-$(date -u +%Y-%m-%d).log"

# Helper: get recent log lines from BOTH journald and openclaw log file
get_recent_logs() {
    # From journald
    journalctl --user -u openclaw --since "$JOURNAL_SINCE" --no-pager 2>/dev/null
    # From openclaw log file (last N minutes, by timestamp filtering)
    if [ -f "$OC_LOG_TODAY" ]; then
        # Extract lines from the log file that are within the stale window
        # The log file has ISO timestamps like "2026-07-22T14:22:54.002+00:00"
        CUTOFF=$(date -u -d "${STALE_MINUTES} min ago" +%Y-%m-%dT%H:%M 2>/dev/null || date -u -v-${STALE_MINUTES}M +%Y-%m-%dT%H:%M 2>/dev/null)
        if [ -n "$CUTOFF" ]; then
            # grep for lines with timestamps >= cutoff (rough filter)
            python3 -c "
import sys, json, datetime
cutoff = datetime.datetime.strptime('$CUTOFF', '%Y-%m-%dT%H:%M')
for line in open('$OC_LOG_TODAY'):
    try:
        d = json.loads(line)
        ts = d.get('time','')
        if ts:
            dt = datetime.datetime.strptime(ts[:16], '%Y-%m-%dT%H:%M')
            if dt >= cutoff:
                msg = d.get('message','') or d.get('1','') or ''
                print(f'{ts} {msg}')
    except:
        pass
" 2>/dev/null
        fi
    fi
}

# Check if the service is active at all
if ! systemctl --user is-active --quiet openclaw; then
    echo "$LOG_PREFIX openclaw not active — attempting restart"
    systemctl --user restart openclaw
    exit 0
fi

# Get combined logs from both sources
ALL_LOGS=$(get_recent_logs)
ENTRIES=$(echo "$ALL_LOGS" | grep -c . 2>/dev/null || echo 0)

if [ "$ENTRIES" -eq 0 ]; then
    echo "$LOG_PREFIX no logs in ${STALE_MINUTES}min — silent hang detected, restarting"
    systemctl --user restart openclaw
    sleep 3
    NEW_PID=$(systemctl --user show openclaw -p MainPID --value)
    echo "$LOG_PREFIX restarted, new PID=$NEW_PID"
    exit 0
fi

# Detect "fetch-timeout storm": ALL recent entries are fetch-timeout errors
TIMEOUT_ENTRIES=$(echo "$ALL_LOGS" | grep -c "fetch-timeout" 2>/dev/null || echo 0)
if [ "$ENTRIES" -gt 0 ] && [ "$TIMEOUT_ENTRIES" -eq "$ENTRIES" ]; then
    echo "$LOG_PREFIX all $ENTRIES entries are fetch-timeouts — proxy-storm hang, restarting"
    systemctl --user restart openclaw
    sleep 3
    NEW_PID=$(systemctl --user show openclaw -p MainPID --value)
    echo "$LOG_PREFIX restarted, new PID=$NEW_PID"
    exit 0
fi

# Detect "agent stuck": inbound message received but no skill/helper/MEDIA activity
INBOUND_COUNT=$(echo "$ALL_LOGS" | grep -c "Inbound message" 2>/dev/null || echo 0)
if [ "$INBOUND_COUNT" -gt 0 ]; then
    SKILL_ACTIVITY=$(echo "$ALL_LOGS" | grep -c -i "styleforge\|run_helper\|helper\|MEDIA:\|skill.*invoke\|POST.*api/runs\|assembler.done\|runner.done" 2>/dev/null || echo 0)
    if [ "$SKILL_ACTIVITY" -eq 0 ]; then
        echo "$LOG_PREFIX inbound=$INBOUND_COUNT but no skill activity=$SKILL_ACTIVITY in ${STALE_MINUTES}min — agent stuck, restarting"
        # Clean up stale sessions before restart
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
