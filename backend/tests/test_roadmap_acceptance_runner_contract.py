from __future__ import annotations

from pathlib import Path


def test_run_roadmap_acceptance_script_supports_strict_gate_envs() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "acceptance" / "run_roadmap_acceptance.sh").read_text(encoding="utf-8")

    assert "ROADMAP_REQUIRE_GO" in script
    assert "ROADMAP_MIN_READINESS_AVG" in script
    assert "ROADMAP_MAX_LOWEST_READINESS_SCORE" in script
    assert "--require-go" in script
    assert "--min-readiness-avg" in script
    assert "--max-lowest-readiness-score" in script
