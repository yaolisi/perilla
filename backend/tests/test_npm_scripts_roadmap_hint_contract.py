from __future__ import annotations

from pathlib import Path


def test_npm_scripts_sh_prints_roadmap_gate_hint_on_default_list() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "npm-scripts.sh"
    content = script.read_text(encoding="utf-8")

    assert (
        "# Roadmap gate npm scripts print stderr hints using `[roadmap-gate]` for CI grep/filter (default/help/--json)."
        in content
    )
    assert (
        "# Errors (missing package.json / unknown flags) also print stderr hints with valid options + `[roadmap-gate]` guidance."
        in content
    )
    assert (
        "#   default    Same as `npm run` (script list/help text on stdout); stderr may print `[roadmap-gate]` hints."
        in content
    )
    assert (
        "#   --json     Print scripts as JSON on stdout (`npm pkg get scripts`); stderr may print `[roadmap-gate]` hints."
        in content
    )
    assert "[roadmap-gate]" in content
    assert "roadmap-acceptance-validate-output" in content
    assert "roadmap-acceptance-run-validated" in content
    assert "roadmap-release-gate" in content
    assert "GET/POST /api/system/roadmap/kpis" in content
    assert "north-star KPI thresholds" in content
    assert "GET /api/system/roadmap/quality-metrics" in content
    assert "explicit_metric_keys" in content
    assert "GET /api/system/roadmap/phases/status" in content
    assert "go_no_go" in content
    assert "phase3_kpi_inference_probe" in content
    assert "print_npm_scripts_error_followups()" in content
    assert "npm-scripts.sh: missing package.json at repo root" in content
    assert 'ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"' in content
    assert (
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: valid options are: (default), --json, --help"'
        in content
    )
    assert (
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: roadmap gate npm scripts emit logs prefixed with ${ROADMAP_GATE_LOG_PREFIX} for CI grep/filter; try: bash scripts/npm-scripts.sh --help"'
        in content
    )
    followups_fn = content.index("print_npm_scripts_error_followups()")
    prefix_def = content.index(
        'ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"'
    )
    miss = content.index("npm-scripts.sh: missing package.json at repo root")
    call_followups = content.index("  print_npm_scripts_error_followups", miss)
    valid = content.index(
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: valid options are: (default), --json, --help"',
        followups_fn,
    )
    gate = content.index(
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: roadmap gate npm scripts emit logs prefixed with ${ROADMAP_GATE_LOG_PREFIX} for CI grep/filter; try: bash scripts/npm-scripts.sh --help"',
        valid,
    )
    print_fn = content.index("print_roadmap_gate_hint()", gate)
    assert prefix_def < followups_fn < miss < call_followups < print_fn
    assert valid < gate
    assert "\n  --json)" in content
    json_case = content.split("\n  --json)", 1)[1].split(";;", 1)[0]
    assert "print_roadmap_gate_hint" in json_case
    assert "npm pkg get scripts" in json_case
    assert "\n  -h|--help)" in content
    help_case = content.split("\n  -h|--help)", 1)[1].split(";;", 1)[0]
    assert "print_roadmap_gate_hint" in help_case
    assert (
        "note: stderr may print `[roadmap-gate]` hints; stdout is npm's script list/help text"
        in help_case
    )
    assert "note: stderr may print `[roadmap-gate]` hints; stdout remains JSON only" in help_case
    assert (
        "note: unknown flags / missing package.json print stderr hints with valid options + `[roadmap-gate]` guidance"
        in help_case
    )
    assert "\n  *)" in content
    unknown_case = content.split("\n  *)", 1)[1].split("esac", 1)[0].split(";;", 1)[0]
    assert 'echo >&2 "npm-scripts.sh: unknown option: ${1}"' in unknown_case
    assert "print_npm_scripts_error_followups" in unknown_case
