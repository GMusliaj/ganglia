#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

scripts/verify.sh

if ! scripts/qmd.sh --version >/dev/null 2>&1; then
  echo "preflight: qmd is not installed" >&2
  exit 1
fi
scripts/qmd.sh status
python3 bin/canvas.py --dry-run

echo "Ganglia golden-path preflight passed."
