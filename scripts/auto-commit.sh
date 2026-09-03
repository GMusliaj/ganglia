#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Security Baseline: Ganglia is not a Git repository; refusing to stage or commit." >&2
  exit 1
fi

python3 bin/reindex.py
python3 bin/artifact_bundle.py validate-tree
if ! python3 bin/lint_ganglia.py; then
  echo "warning: Ganglia lint reported advisory issues; security checks will still run." >&2
fi
python3 scripts/guard_shared.py
python3 scripts/commit_shared.py
