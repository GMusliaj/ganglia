#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
mkdir -p "$BRAIN_ROOT/local/notes" "$BRAIN_ROOT/local/projects" "$BRAIN_ROOT/local/short-mem"

if [ ! -f "$BRAIN_ROOT/local/shared-denylist.txt" ]; then
  cp "$BRAIN_ROOT/scripts/templates/shared-denylist.txt" "$BRAIN_ROOT/local/shared-denylist.txt"
fi

python3 "$BRAIN_ROOT/bin/reindex.py"
