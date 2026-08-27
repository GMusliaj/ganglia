#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"

if [ -s "${HOME}/.nvm/nvm.sh" ]; then
  # NVM is intentionally scoped to this process; this does not change the
  # user's default Node version.
  # shellcheck disable=SC1091
  . "${HOME}/.nvm/nvm.sh"
  nvm use --silent "$(cat "$BRAIN_ROOT/.nvmrc")" >/dev/null
fi

cd "$BRAIN_ROOT"
exec qmd "$@"
