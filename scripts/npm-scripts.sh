#!/usr/bin/env bash
set -euo pipefail
# Lists scripts from repo root package.json (`npm run` with no script name).
#   default    Same as `npm run` (script list/help text on stdout); stderr may print `[roadmap-gate]` hints.
#   --json     Print scripts as JSON on stdout (`npm pkg get scripts`); stderr may print `[roadmap-gate]` hints.
#   -h, --help Usage.
# Roadmap gate npm scripts print stderr hints using `[roadmap-gate]` for CI grep/filter (default/help/--json).
# Errors (missing package.json / unknown flags) also print stderr hints with valid options + `[roadmap-gate]` guidance.
# Prefer `bash scripts/npm-scripts.sh` from any cwd; `npm run npm-scripts` needs cwd at repo root.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"
print_npm_scripts_error_followups() {
  echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: valid options are: (default), --json, --help"
  echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: roadmap gate npm scripts emit logs prefixed with ${ROADMAP_GATE_LOG_PREFIX} for CI grep/filter; try: bash scripts/npm-scripts.sh --help"
}
if [[ ! -f package.json ]]; then
  echo >&2 "npm-scripts.sh: missing package.json at repo root (${ROOT}); is this script path correct?"
  print_npm_scripts_error_followups
  exit 1
fi
print_roadmap_gate_hint() {
  cat >&2 <<'EOF'
npm-scripts hint: roadmap gate helpers (`npm run roadmap-acceptance-validate-output`,
`npm run roadmap-acceptance-run-validated`, `npm run roadmap-release-gate`) emit logs prefixed with
`[roadmap-gate]` for CI grep/filter (same convention as `make help`).
npm-scripts hint: GET/POST /api/system/roadmap/kpis (platform admin) reads/saves merged north-star KPI thresholds
(see also `make help`).
npm-scripts hint: GET /api/system/roadmap/quality-metrics (platform admin) returns merged quality metrics,
explicit_metric_keys, phase3_kpi_inference_probe (see also `make help`).
npm-scripts hint: GET /api/system/roadmap/phases/status (platform admin) returns snapshot, north_star, phase_gate,
go_no_go (see also `make help`).
npm-scripts hint: POST /api/system/roadmap/phase-gates (platform admin) merges persisted phase gate overrides (see also `make help`).
npm-scripts hint: GET /api/system/roadmap/monthly-review (platform admin) lists paginated monthly reviews with filter meta (see also `make help`).
npm-scripts hint: POST /api/system/roadmap/monthly-review (platform admin) appends a gated snapshot review (see also `make help`).
EOF
}
case "${1:-}" in
  "")
    print_roadmap_gate_hint
    exec npm run
    ;;
  --json)
    print_roadmap_gate_hint
    npm pkg get scripts
    ;;
  -h|--help)
    print_roadmap_gate_hint
    printf '%s\n' \
      "usage: bash scripts/npm-scripts.sh [--json|--help]" \
      "  default   list scripts (same as npm run)" \
      "            note: stderr may print `[roadmap-gate]` hints; stdout is npm's script list/help text" \
      "  --json    npm pkg get scripts" \
      "            note: stderr may print `[roadmap-gate]` hints; stdout remains JSON only" \
      "            note: unknown flags / missing package.json print stderr hints with valid options + `[roadmap-gate]` guidance"
    exit 0
    ;;
  *)
    echo >&2 "npm-scripts.sh: unknown option: ${1}"
    print_npm_scripts_error_followups
    exit 1
    ;;
esac
