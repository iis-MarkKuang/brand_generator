#!/usr/bin/env bash
# CP-015 — automatable CP acceptance harness (lightweight CI stand-in).
#
# Runs every CP's automatable acceptance items (lint, typecheck, unit + golden
# tests, secrets scan, env validation) and prints a pass/fail summary. Live-model
# smokes + manual demo steps are NOT included (they need GPU + real keys).
set -u
cd "$(dirname "$0")/.."

export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple/}"

PASS=0
FAIL=0
RESULTS=()

run() {  # name  command...
  local name="$1"; shift
  printf '  ◷ %-22s ' "$name"
  if "$@" >/tmp/styleforge_acceptance.log 2>&1; then
    printf '\033[32mPASS\033[0m\n'
    PASS=$((PASS + 1))
    RESULTS+=("PASS  $name")
  else
    printf '\033[31mFAIL\033[0m\n'
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL  $name")
    tail -n 12 /tmp/styleforge_acceptance.log | sed 's/^/      | /'
  fi
}

echo "StyleForge acceptance harness (CP-015)"
echo "======================================"

run "ruff lint"          uv run ruff check .
run "ruff format"        uv run ruff format --check .
run "mypy typecheck"     uv run mypy src
run "unit + golden tests" uv run pytest -q
run "secrets scan"       bash tools/check-secrets.sh
run "golden fixtures"    uv run pytest tests/test_golden.py -q

echo
echo "======================================"
echo "  PASS: $PASS   FAIL: $FAIL"
echo "======================================"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
