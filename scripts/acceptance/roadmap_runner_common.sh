#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"

run_roadmap_make_target() {
  local target="$1"
  shift || true

  cd "$ROOT"
  make "$target" "$@"
  local status=$?
  if [[ $status -ne 0 ]]; then
    echo "${ROADMAP_GATE_LOG_PREFIX} ${target} failed (exit=${status})" >&2
    echo "${ROADMAP_GATE_LOG_PREFIX} hint: exit=2 means parameter/input error; exit=1 means contract/business validation failure" >&2
  fi
  return "$status"
}
