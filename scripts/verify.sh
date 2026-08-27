#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/guard_shared.py
python3 bin/reindex.py
python3 bin/lint_brain.py

for script in scripts/*.sh; do
  bash -n "$script"
done

SKILL_CREATOR_ROOT="${CODEX_HOME:-${HOME}/.codex}/skills/.system/skill-creator"
if [ -f "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" ] && python3 -c 'import yaml' >/dev/null 2>&1; then
  python3 "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" .agents/skills/remember
  python3 "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" .agents/skills/recall
elif [ -f "$SKILL_CREATOR_ROOT/scripts/quick_validate.py" ]; then
  echo "warning: skipped official skill validator because PyYAML is unavailable" >&2
fi
