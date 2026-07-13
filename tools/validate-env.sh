#!/usr/bin/env bash
# Verify all required env vars are present in .env (without printing values).
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

if [[ ! -f .env ]]; then
  echo "FAIL: .env not found. Copy .env.example to .env and fill in values." >&2
  exit 1
fi

required=(
  STEPFUN_API_KEY STEPFUN_BASE_URL STEPFUN_VLM_MODEL
  NVIDIA_API_KEY NVIDIA_NIM_BASE_URL NVIDIA_NIM_MODEL
  HF_TOKEN TELEGRAM_BOT_TOKEN
  OLLAMA_HOST OLLAMA_REASONING_MODEL COMFYUI_HOST
  OPENCLAW_HOME OPENCLAW_PORT
  APP_PORT FRONTEND_PORT
)

# shellcheck disable=SC1091
set +u; set -a; . ./.env; set +a; set -u

rc=0
for var in "${required[@]}"; do
  val="${!var:-}"
  if [[ -z "$val" || "$val" == replace_with_your_* ]]; then
    echo "MISSING: $var (still a placeholder or unset)" >&2
    rc=1
  fi
done
[[ $rc -eq 0 ]] && echo "OK: all required env vars present." || echo "FAIL: see missing vars above." >&2
exit $rc
