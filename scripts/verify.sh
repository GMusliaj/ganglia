#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

BRAIN_PYTHON="$BRAIN_ROOT/.venv/bin/python"
if [ ! -x "$BRAIN_PYTHON" ]; then
  echo "error: repository Python environment is missing; run scripts/setup-python.sh" >&2
  exit 1
fi

"$BRAIN_PYTHON" -m unittest discover -s tests -p 'test_*.py'
ARTIFACT_EVAL_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/brain-artifact-eval.XXXXXX")"
trap 'rm -f -- "$ARTIFACT_EVAL_OUTPUT"' EXIT
"$BRAIN_PYTHON" scripts/eval_artifacts.py --output "$ARTIFACT_EVAL_OUTPUT"
"$BRAIN_PYTHON" scripts/guard_shared.py
"$BRAIN_PYTHON" bin/reindex.py
"$BRAIN_PYTHON" bin/lint_brain.py

for script in scripts/*.sh; do
  bash -n "$script"
done

SKILL_CREATOR_ROOT="${CODEX_HOME:-${HOME}/.codex}/skills/.system/skill-creator"
if [ -f "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" ]; then
  "$BRAIN_PYTHON" -c 'import yaml'
  "$BRAIN_PYTHON" "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" .agents/skills/remember
  "$BRAIN_PYTHON" "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" .agents/skills/recall
fi
