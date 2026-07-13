#!/usr/bin/env bash
# Scaffold a new change packet from specs/_template.md
# Usage: tools/new-change-packet.sh "Short title of the work"
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
title="${1:-}"
if [[ -z "$title" ]]; then
  echo "usage: tools/new-change-packet.sh \"Short title of the work\"" >&2
  exit 2
fi

# next number
shopt -s nullglob
existing=( specs/CP-???-*.md )
next=1
if [[ ${#existing[@]} -gt 0 ]]; then
  nums=$(printf '%s\n' "${existing[@]}" | sed -E 's#specs/CP-([0-9]+)-.*#\1#' | sort -n)
  next=$(( $(printf '%s\n' "$nums" | tail -n1) + 1 ))
fi
nnn=$(printf '%03d' "$next")

# slug
slug=$(echo "$title" | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/--+/-/g' | cut -c1-50)
file="specs/CP-${nnn}-${slug}.md"

cp specs/_template.md "$file"
# fill title placeholder
perl -pi -e "s/<title>/\Q$title\E/" "$file"

echo "Created: $file"
echo "Next: add it to specs/ROADMAP.md and branch with: git checkout -b cp-${nnn}-${slug}"
