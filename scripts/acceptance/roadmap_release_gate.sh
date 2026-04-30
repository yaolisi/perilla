#!/usr/bin/env bash
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/roadmap_runner_common.sh"

ROADMAP_MAKE_TARGET="roadmap-release-gate"
run_roadmap_make_target "$ROADMAP_MAKE_TARGET" "$@"
