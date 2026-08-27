#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
SKILL_HOME="${HOME}/.agents/skills"
PROMPT_HOME="${CODEX_HOME:-${HOME}/.codex}/prompts"

mkdir -p "$SKILL_HOME" "$PROMPT_HOME"

install_link() {
  SOURCE_PATH="$1"
  TARGET_PATH="$2"

  if [ -L "$TARGET_PATH" ] && [ "$(readlink "$TARGET_PATH")" = "$SOURCE_PATH" ]; then
    return 0
  fi
  if [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
    echo "Refusing to overwrite existing command path: $TARGET_PATH" >&2
    exit 1
  fi
  ln -s "$SOURCE_PATH" "$TARGET_PATH"
}

install_link "$BRAIN_ROOT/.agents/skills/remember" "$SKILL_HOME/remember"
install_link "$BRAIN_ROOT/.agents/skills/recall" "$SKILL_HOME/recall"
install_link "$BRAIN_ROOT/prompts/remember.md" "$PROMPT_HOME/remember.md"
install_link "$BRAIN_ROOT/prompts/recall.md" "$PROMPT_HOME/recall.md"

echo "Installed Brain commands. Use \$remember / \$recall, or /prompts:remember / /prompts:recall after restarting Codex."
