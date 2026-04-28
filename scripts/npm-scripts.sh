#!/usr/bin/env bash
set -euo pipefail
# Lists scripts from repo root package.json (`npm run` with no script name).
#   --json     Print scripts as JSON (npm pkg get scripts).
#   -h, --help Usage.
# Prefer `bash scripts/npm-scripts.sh` from any cwd; `npm run npm-scripts` needs cwd at repo root.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f package.json ]]; then
  echo >&2 "npm-scripts.sh: missing package.json at repo root (${ROOT}); is this script path correct?"
  exit 1
fi
case "${1:-}" in
  "")       exec npm run ;;
  --json)   npm pkg get scripts ;;
  -h|--help)
    printf '%s\n' \
      "usage: bash scripts/npm-scripts.sh [--json|--help]" \
      "  default   list scripts (same as npm run)" \
      "  --json    npm pkg get scripts"
    exit 0
    ;;
  *)
    echo >&2 "npm-scripts.sh: unknown option: ${1}"
    exit 1
    ;;
esac
