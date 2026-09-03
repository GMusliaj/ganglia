#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

BRAIN_PYTHON="$BRAIN_ROOT/.venv/bin/python"
if [ ! -x "$BRAIN_PYTHON" ]; then
  echo "error: repository Python environment is missing; run scripts/setup-python.sh" >&2
  exit 1
fi

scripts/audit-security.sh --offline
"$BRAIN_PYTHON" -m unittest discover -s tests -p 'test_*.py'
"$BRAIN_PYTHON" scripts/eval_skills.py
ARTIFACT_EVAL_OUTPUT="$(mktemp "${TMPDIR:-/tmp}/ganglia-artifact-eval.XXXXXX")"
trap 'rm -f -- "$ARTIFACT_EVAL_OUTPUT"' EXIT
"$BRAIN_PYTHON" scripts/eval_artifacts.py --output "$ARTIFACT_EVAL_OUTPUT"
"$BRAIN_PYTHON" scripts/guard_shared.py
"$BRAIN_PYTHON" bin/reindex.py
"$BRAIN_PYTHON" bin/lint_ganglia.py

"$BRAIN_PYTHON" bin/skill_evolution.py validate-skill \
  .agents/skills/remember \
  .agents/skills/recall \
  .agents/skills/fafo \
  .agents/skills/skill-evolution
