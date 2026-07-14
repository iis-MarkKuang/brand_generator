#!/usr/bin/env bash
# OpenClaw entrypoint for the StyleForge skill.
# Lives at: $OPENCLAW_HOME/.openclaw/skills/styleforge/run_helper.sh
# It holds NO secrets and does NOT load .env — it only talks to the local
# FastAPI orchestrator at http://127.0.0.1:8000 (single secrets boundary,
# references/design/07-security-and-tokens.md §A). Safe inside the NemoClaw
# sandbox (CP-012).
#
# Usage:
#   run_helper.sh "<brief>"            [assets]
#   run_helper.sh "<brief>" "logo,social_square,hero_banner"
# The reference image is auto-discovered from OpenClaw's inbound directory
# (newest image), matching the workshop skill convention.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# OPENCLAW_HOME is injected by the gateway; fall back to the workshop layout.
if [ -z "${OPENCLAW_HOME:-}" ]; then
    OPENCLAW_HOME="$(cd "$SCRIPT_DIR/../../.." && pwd)"
    export OPENCLAW_HOME
fi

# The orchestrator API base (no secrets here — just the host orchestrator).
# Auto-detect: inside the NemoClaw sandbox (/.dockerenv present) the backend
# runs on the HOST, so reach it via host.openshell.internal (OpenShell's host
# alias; the local-inference preset already allowlists host.openshell.internal:8000
# with the SSRF-guard allowed_ips). On the host itself 127.0.0.1 is correct.
# An explicit STYLEFORGE_API always wins.
if [ -z "${STYLEFORGE_API:-}" ]; then
    if [ -f /.dockerenv ]; then
        export STYLEFORGE_API="http://host.openshell.internal:8000"
    else
        export STYLEFORGE_API="http://127.0.0.1:8000"
    fi
fi

# CP-017: map gateway Telegram env to generic helper env (keeps helper secrets-free).
# The helper uses STYLEFORGE_TG_TOKEN / STYLEFORGE_TG_CHAT — never reads TELEGRAM_* directly.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -z "${STYLEFORGE_TG_TOKEN:-}" ]; then
    export STYLEFORGE_TG_TOKEN="$TELEGRAM_BOT_TOKEN"
fi
if [ -n "${TELEGRAM_ALLOWED_CHAT_IDS:-}" ] && [ -z "${STYLEFORGE_TG_CHAT:-}" ]; then
    export STYLEFORGE_TG_CHAT="$TELEGRAM_ALLOWED_CHAT_IDS"
fi

exec python3 "$SCRIPT_DIR/styleforge_helper.py" "$@"
