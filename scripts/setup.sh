#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

scripts/setup-python.sh
scripts/init.sh
scripts/install-codex-commands.sh
scripts/install-qmd-mcp.sh

if command -v npm >/dev/null 2>&1; then
  npm install --prefix bin
else
  echo "warning: npm is unavailable; run 'npm install --prefix bin' before building the canvas" >&2
fi

if scripts/qmd.sh --version >/dev/null 2>&1; then
  scripts/refresh-qmd.sh
fi

scripts/verify.sh
