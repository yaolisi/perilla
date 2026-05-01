from __future__ import annotations

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_makefile_roadmap_release_gate_has_strict_defaults() -> None:
    root = repo_root()
    makefile = (root / "Makefile").read_text(encoding="utf-8")

    assert "roadmap-release-gate:" in makefile
    assert 'ROADMAP_REQUIRE_GO="$(or $(ROADMAP_REQUIRE_GO),1)"' in makefile
    assert 'ROADMAP_MIN_READINESS_AVG="$(or $(ROADMAP_MIN_READINESS_AVG),0.8)"' in makefile
    assert 'ROADMAP_MAX_LOWEST_READINESS_SCORE="$(or $(ROADMAP_MAX_LOWEST_READINESS_SCORE),0.7)"' in makefile
    assert "ROADMAP_OUTPUT_JSON ?=" in makefile
    assert "ROADMAP_OUTPUT_SCHEMA_VERSION ?= 1" in makefile
    assert "ROADMAP_GATE_LOG_PREFIX ?= [roadmap-gate]" in makefile
    assert '--output-json "$(ROADMAP_OUTPUT_JSON)"' in makefile
    assert "roadmap-acceptance-validate-schema-version:" in makefile
    assert "roadmap-acceptance-validate-output:" in makefile
    assert "roadmap-acceptance-run-validated:" in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance unit start"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance unit done"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance smoke start"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance smoke done"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance all start"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) roadmap acceptance all done"' in makefile
    assert 'ROADMAP_GATE_LOG_PREFIX="$(ROADMAP_GATE_LOG_PREFIX)"' in makefile
    assert "ROADMAP_OUTPUT_SCHEMA_VERSION must be a positive integer" in makefile
    assert "ROADMAP_OUTPUT_JSON must be non-empty" in makefile
    assert "file=sys.stderr" in makefile
    assert "prefix='$(ROADMAP_GATE_LOG_PREFIX)'" in makefile
    assert "p='$(ROADMAP_GATE_LOG_PREFIX)'" in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) validating roadmap output artifact"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) run+validate roadmap acceptance flow"' in makefile
    assert 'echo "$(ROADMAP_GATE_LOG_PREFIX) strict release gate start"' in makefile
    assert "validate_roadmap_acceptance_result.py" in makefile
    assert "$(MAKE) roadmap-acceptance-run-validated" in makefile
