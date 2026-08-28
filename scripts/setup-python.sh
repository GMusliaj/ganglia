#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
BRAIN_VENV="$BRAIN_ROOT/.venv"
BRAIN_PYTHON="$BRAIN_VENV/bin/python"

if [ ! -x "$BRAIN_PYTHON" ]; then
  python3 -m venv "$BRAIN_VENV"
fi

"$BRAIN_PYTHON" -m pip install \
  --disable-pip-version-check \
  --require-virtualenv \
  -r "$BRAIN_ROOT/requirements-dev.txt"
