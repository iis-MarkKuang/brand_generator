#!/usr/bin/env bash
# Fail if any known secret value appears in tracked or staged files.
# Run before every commit. Never prints secret values themselves.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Known secret values (loaded from .env, never echoed).
declare -A SECRETS=()
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set +u; set -a; . ./.env; set +a; set -u
  for var in STEPFUN_API_KEY NVIDIA_API_KEY HF_TOKEN TELEGRAM_BOT_TOKEN; do
    val="${!var:-}"
    [[ -n "$val" ]] && SECRETS["$var"]="$val"
  done
fi

rc=0

# 1) .env must never be tracked or staged
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked by git. Untrack it: git rm --cached .env" >&2
  rc=1
fi
if git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep -qx '.env'; then
  echo "FAIL: .env is staged for commit. Unstage it: git reset HEAD .env" >&2
  rc=1
fi

# 2) build the file list to scan: tracked + newly staged, minus .env/.env.*
mapfile -t TRACKED < <(git ls-files 2>/dev/null || true)
mapfile -t STAGED  < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
SCAN=()
declare -A _seen=()
for f in "${TRACKED[@]}" "${STAGED[@]}"; do
  [[ -z "$f" ]] && continue
  [[ -n "${_seen[$f]:-}" ]] && continue
  case "$f" in
    .env|.env.*) continue ;;   # never scan env files even if somehow listed
  esac
  _seen[$f]=1
  SCAN+=("$f")
done

# 3) scan explicit file list only (never stdin)
if [[ ${#SCAN[@]} -gt 0 && ${#SECRETS[@]} -gt 0 ]]; then
  for var in "${!SECRETS[@]}"; do
    val="${SECRETS[$var]}"
    [[ "$val" == replace_with_your_* ]] && continue
    hits=$(grep -rlIF -- "$val" "${SCAN[@]}" 2>/dev/null || true)
    if [[ -n "$hits" ]]; then
      echo "FAIL: secret value for $var found in tracked/staged file(s):" >&2
      printf '%s\n' "$hits" >&2
      rc=1
    fi
  done
fi

[[ $rc -eq 0 ]] && echo "OK: no secrets detected in tracked/staged content." || echo "FAIL: secrets check failed." >&2
exit $rc
