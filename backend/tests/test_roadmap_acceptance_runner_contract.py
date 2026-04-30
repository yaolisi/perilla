from __future__ import annotations

from pathlib import Path


def test_run_roadmap_acceptance_script_supports_strict_gate_envs() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "acceptance" / "run_roadmap_acceptance.sh").read_text(encoding="utf-8")

    assert 'ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"' in script
    assert (
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} hint: live smoke exercises GET/POST /api/system/roadmap/kpis and POST /api/system/roadmap/quality-metrics (platform admin; see make help)"'
        in script
    )
    assert 'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} roadmap acceptance: unit/integration suite"' in script
    assert 'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} roadmap acceptance: live API smoke"' in script
    assert (
        'echo >&2 "${ROADMAP_GATE_LOG_PREFIX} skip live smoke (set ROADMAP_RUN_LIVE_SMOKE=1 to enable)"'
        in script
    )
    assert "ROADMAP_REQUIRE_GO" in script
    assert "ROADMAP_MIN_READINESS_AVG" in script
    assert "ROADMAP_MAX_LOWEST_READINESS_SCORE" in script
    assert "ROADMAP_OUTPUT_JSON" in script
    assert "ROADMAP_OUTPUT_SCHEMA_VERSION" in script
    assert "--require-go" in script
    assert "--min-readiness-avg" in script
    assert "--max-lowest-readiness-score" in script
    assert "--output-json" in script
    assert "validate_roadmap_acceptance_result.py" in script
