#!/bin/bash
set -euo pipefail

BRAIN_ROOT="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)"
BRAIN_PYTHON="$BRAIN_ROOT/.venv/bin/python"
BRAIN_SHELLCHECK="$BRAIN_ROOT/.venv/bin/shellcheck"
BRAIN_ESLINT="$BRAIN_ROOT/bin/node_modules/.bin/eslint"
BRAIN_PIP_CACHE="$BRAIN_ROOT/.tmp/pip-cache"
BRAIN_PIP_AUDIT_CACHE="$BRAIN_ROOT/.tmp/pip-audit-cache"
BRAIN_MODE="full"

usage() {
  cat <<'EOF'
Usage: scripts/audit-security.sh [--offline]

Run Ganglia's security scanners over every tracked or non-ignored Python, Bash,
and JavaScript source file. The default also performs live Python and npm
advisory lookups. --offline runs only deterministic local checks.
EOF
}

case "${1:-}" in
  "") ;;
  --offline) BRAIN_MODE="offline" ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [ "$#" -gt 1 ]; then
  usage >&2
  exit 2
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required security tool is unavailable: $1" >&2
    exit 1
  fi
}

require_executable() {
  if [ ! -x "$1" ]; then
    echo "error: required security tool is unavailable: $1; run scripts/setup-python.sh and npm install --prefix bin" >&2
    exit 1
  fi
}

run_step() {
  printf '\n==> %s\n' "$1"
  shift
  "$@"
}

require_command git
require_command bash
require_command node
require_command npm
require_executable "$BRAIN_PYTHON"
require_executable "$BRAIN_SHELLCHECK"
require_executable "$BRAIN_ESLINT"

cd "$BRAIN_ROOT"
mkdir -p "$BRAIN_PIP_CACHE"
export PIP_CACHE_DIR="$BRAIN_PIP_CACHE"

BRAIN_PYTHON_FILES=()
while IFS= read -r -d '' file; do
  BRAIN_PYTHON_FILES+=("$file")
done < <(git ls-files --cached --others --exclude-standard -z -- '*.py')

BRAIN_SHELL_FILES=()
while IFS= read -r -d '' file; do
  BRAIN_SHELL_FILES+=("$file")
done < <(git ls-files --cached --others --exclude-standard -z -- '*.sh')

BRAIN_JAVASCRIPT_FILES=()
while IFS= read -r -d '' file; do
  BRAIN_JAVASCRIPT_FILES+=("$file")
done < <(git ls-files --cached --others --exclude-standard -z -- '*.js' '*.mjs')

if [ "${#BRAIN_PYTHON_FILES[@]}" -eq 0 ] || [ "${#BRAIN_SHELL_FILES[@]}" -eq 0 ] || [ "${#BRAIN_JAVASCRIPT_FILES[@]}" -eq 0 ]; then
  echo "error: security source inventory is unexpectedly empty" >&2
  exit 1
fi

run_step "Python environment consistency" "$BRAIN_PYTHON" -m pip check
run_step "Python source security (Bandit medium+)" \
  "$BRAIN_PYTHON" -m bandit \
  --quiet \
  --severity-level medium \
  --confidence-level medium \
  "${BRAIN_PYTHON_FILES[@]}"

printf '\n==> Bash syntax\n'
for file in "${BRAIN_SHELL_FILES[@]}"; do
  bash -n "$file"
done

run_step "Bash source analysis (ShellCheck warning+)" \
  "$BRAIN_SHELLCHECK" --severity=warning --external-sources "${BRAIN_SHELL_FILES[@]}"

printf '\n==> JavaScript syntax\n'
for file in "${BRAIN_JAVASCRIPT_FILES[@]}"; do
  node --check "$file"
done

run_step "JavaScript source security (ESLint)" npm run --prefix bin lint:security
printf '\n==> Installed npm dependency consistency\n'
npm ls --prefix bin --all >/dev/null

if [ "$BRAIN_MODE" = "offline" ]; then
  printf '\nSecurity static analysis passed; live advisory lookups were skipped (--offline).\n'
  exit 0
fi

mkdir -p "$BRAIN_PIP_AUDIT_CACHE"
for service in pypi osv; do
  run_step "Installed Python environment advisory audit ($service)" \
    "$BRAIN_PYTHON" -m pip_audit \
    --strict \
    --local \
    --progress-spinner off \
    --desc off \
    --aliases on \
    --timeout 30 \
    --cache-dir "$BRAIN_PIP_AUDIT_CACHE" \
    --vulnerability-service "$service"

  run_step "Declared Python requirements advisory audit ($service)" \
    "$BRAIN_PYTHON" -m pip_audit \
    --strict \
    --requirement requirements-dev.txt \
    --progress-spinner off \
    --desc off \
    --aliases on \
    --timeout 30 \
    --cache-dir "$BRAIN_PIP_AUDIT_CACHE" \
    --vulnerability-service "$service"
done

run_step "npm dependency advisory audit" npm audit --prefix bin --audit-level=low

printf '\nSecurity audit passed. QMD is an optional host-installed dependency and is not covered by the repository lockfiles.\n'
