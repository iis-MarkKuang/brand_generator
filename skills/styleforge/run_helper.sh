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

# The orchestrator API base (no secrets here — just localhost).
export STYLEFORGE_API="${STYLEFORGE_API:-http://127.0.0.1:8000}"

exec python3 "$SCRIPT_DIR/styleforge_helper.py" "$@"
