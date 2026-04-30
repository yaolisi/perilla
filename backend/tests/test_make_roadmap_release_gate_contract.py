from __future__ import annotations

from pathlib import Path


def test_makefile_roadmap_release_gate_has_strict_defaults() -> None:
    root = Path(__file__).resolve().parents[2]
    makefile = (root / "Makefile").read_text(encoding="utf-8")

    assert "roadmap-release-gate:" in makefile
    assert 'ROADMAP_REQUIRE_GO="$(or $(ROADMAP_REQUIRE_GO),1)"' in makefile
    assert 'ROADMAP_MIN_READINESS_AVG="$(or $(ROADMAP_MIN_READINESS_AVG),0.8)"' in makefile
    assert 'ROADMAP_MAX_LOWEST_READINESS_SCORE="$(or $(ROADMAP_MAX_LOWEST_READINESS_SCORE),0.7)"' in makefile
