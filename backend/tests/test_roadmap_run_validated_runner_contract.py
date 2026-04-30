from __future__ import annotations

from pathlib import Path


def test_roadmap_run_validated_runner_keeps_exit_code_hint_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "acceptance" / "roadmap_run_validated.sh"
    content = script.read_text(encoding="utf-8")

    assert "roadmap_runner_common.sh" in content
    assert 'ROADMAP_MAKE_TARGET="roadmap-acceptance-run-validated"' in content
    assert 'run_roadmap_make_target "$ROADMAP_MAKE_TARGET" "$@"' in content
