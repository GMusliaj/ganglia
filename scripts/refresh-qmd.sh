#!/bin/bash
set -u

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

if ! scripts/qmd.sh --version >/dev/null 2>&1; then
  exit 0
fi

if ! scripts/qmd.sh collection list 2>/dev/null | grep -qE '(^|[[:space:]])brain([[:space:]]|$)'; then
  exit 0
fi

python3 bin/sync_codex_sessions.py
scripts/qmd.sh update
status=0
scripts/qmd.sh embed -c brain || status=$?
scripts/qmd.sh embed -c codex-sessions || status=$?
exit "$status"
