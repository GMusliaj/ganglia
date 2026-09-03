#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
SERVER_NAME="ganglia-qmd"

if ! command -v codex >/dev/null 2>&1; then
  echo "warning: Codex CLI is unavailable; configure the ganglia-qmd MCP server later" >&2
  exit 0
fi

if codex mcp get "$SERVER_NAME" >/dev/null 2>&1; then
  echo "Ganglia QMD MCP server is already configured."
  exit 0
fi

codex mcp add "$SERVER_NAME" -- "$BRAIN_ROOT/scripts/qmd.sh" mcp
