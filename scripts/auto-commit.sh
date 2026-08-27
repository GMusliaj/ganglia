#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$BRAIN_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Security Baseline: Brain is not a Git repository; refusing to stage or commit." >&2
  exit 1
fi

python3 bin/reindex.py
if ! python3 bin/lint_brain.py; then
  echo "warning: Brain lint reported advisory issues; security checks will still run." >&2
fi
python3 scripts/guard_shared.py

git add -- MEMORY.md patterns lessons decisions concepts snippets sources infra meta/tag-taxonomy.md

if git diff --cached --quiet --; then
  echo "No shared knowledge changes to commit."
  exit 0
fi

CHANGED_FILES="$(git diff --cached --name-only --diff-filter=ACMR)"
CHANGED_COUNT="$(printf '%s\n' "$CHANGED_FILES" | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "$CHANGED_COUNT" = "1" ]; then
  CHANGED_NAME="$(basename -- "$CHANGED_FILES" .md)"
  COMMIT_MESSAGE="brain: update $CHANGED_NAME"
else
  COMMIT_MESSAGE="brain: update $CHANGED_COUNT knowledge files"
fi

git commit -m "$COMMIT_MESSAGE"
