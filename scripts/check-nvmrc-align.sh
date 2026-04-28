#!/usr/bin/env bash
set -euo pipefail
# Ensure repo root `.nvmrc` matches `frontend/.nvmrc` (same bytes). Run from repository root.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f .nvmrc ]]; then
  echo >&2 "check-nvmrc-align.sh: missing repo root .nvmrc (${ROOT})"
  exit 1
fi
if [[ ! -f frontend/.nvmrc ]]; then
  echo >&2 "check-nvmrc-align.sh: missing frontend/.nvmrc (${ROOT})"
  exit 1
fi
if cmp -s .nvmrc frontend/.nvmrc; then
  exit 0
fi
echo >&2 "Error: .nvmrc and frontend/.nvmrc must match"
exit 1
