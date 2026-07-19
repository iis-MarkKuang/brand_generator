#!/usr/bin/env bash
# cleanup-runs.sh — remove stale/incomplete runs and helper temp state.
#
# Keeps:
#   - golden-001, test-run-001 (test fixtures referenced by tests)
#   - the N most recent *assembled* runs (default 3)
# Removes:
#   - all incomplete/failed runs (no brand_kit/kit_manifest.json)
#   - old assembled runs beyond the keep-N window
#   - helper temp files (/tmp/styleforge_helper_*) that hold stale
#     debounce / dedup / run-count state from previous sessions
#
# Usage:  ./tools/cleanup-runs.sh [--keep N] [--dry-run]
set -euo pipefail

KEEP=3
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --keep) shift; KEEP="$1"; shift ;;
        --dry-run) DRY_RUN=1 ;;
    esac
done

cd "$(dirname "$0")/.."
RUNS_DIR="runs"
REMOVED=0
KEPT=0

# 1. Always-keep fixtures
FIXTURES="golden-001 test-run-001"

# 2. Remove incomplete runs (no kit_manifest.json)
echo "=== Phase 1: incomplete runs ==="
for d in "$RUNS_DIR"/*/; do
    id=$(basename "$d")
    case " $FIXTURES " in *" $id "*) continue ;; esac
    if [ ! -f "${d}brand_kit/kit_manifest.json" ]; then
        echo "  DEL (incomplete)  $id"
        [ "$DRY_RUN" -eq 0 ] && rm -rf "$d"
        REMOVED=$((REMOVED+1))
    fi
done

# 3. Among assembled runs, keep only the N most recent
echo "=== Phase 2: old assembled runs (keep=$KEEP) ==="
mapfile -t ASSEMBLED < <(
    for d in "$RUNS_DIR"/*/; do
        id=$(basename "$d")
        case " $FIXTURES " in *" $id "*) continue ;; esac
        [ -f "${d}brand_kit/kit_manifest.json" ] || continue
        stat -c "%Y %n" "${d}brand_kit/kit_manifest.json"
    done | sort -rn
)
IDX=0
for line in "${ASSEMBLED[@]}"; do
    IDX=$((IDX+1))
    run_dir=$(dirname "$(dirname "$line" | awk '{print $2}')")
    id=$(basename "$run_dir")
    if [ "$IDX" -le "$KEEP" ]; then
        echo "  KEEP ($IDX)         $id"
        KEPT=$((KEPT+1))
    else
        echo "  DEL (old,rank=$IDX) $id"
        [ "$DRY_RUN" -eq 0 ] && rm -rf "$run_dir"
        REMOVED=$((REMOVED+1))
    fi
done

# 4. Keep fixtures
echo "=== Phase 3: fixtures ==="
for f in $FIXTURES; do
    if [ -d "$RUNS_DIR/$f" ]; then
        echo "  KEEP (fixture)     $f"
        KEPT=$((KEPT+1))
    fi
done

# 5. Clean helper temp state (stale debounce / dedup / run-count)
echo "=== Phase 4: helper temp state ==="
for f in /tmp/styleforge_helper_last_brief.hash \
         /tmp/styleforge_helper_last_run.ts \
         /tmp/styleforge_helper_run_count.log; do
    if [ -e "$f" ]; then
        echo "  DEL (tmp)          $f"
        [ "$DRY_RUN" -eq 0 ] && rm -f "$f"
    fi
done

echo ""
echo "Summary: removed=$REMOVED kept=$KEPT dry_run=$DRY_RUN"
