#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
BRAIN_VENV="$BRAIN_ROOT/.venv"
BRAIN_PYTHON="$BRAIN_VENV/bin/python"
BRAIN_PIP_VERSION="26.2.1"

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "error: Ganglia tooling requires Python 3.10 or newer" >&2
  exit 1
fi

if [ ! -x "$BRAIN_PYTHON" ]; then
  python3 -m venv "$BRAIN_VENV"
fi

"$BRAIN_PYTHON" -m pip install \
  --disable-pip-version-check \
  --require-virtualenv \
  "pip==$BRAIN_PIP_VERSION"

"$BRAIN_PYTHON" -m pip install \
  --disable-pip-version-check \
  --require-virtualenv \
  -r "$BRAIN_ROOT/requirements-dev.txt"
