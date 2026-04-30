from __future__ import annotations

from pathlib import Path


def test_roadmap_validate_output_runner_keeps_exit_code_hint_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "acceptance" / "roadmap_validate_output.sh"
    content = script.read_text(encoding="utf-8")

    assert "roadmap_runner_common.sh" in content
    assert 'ROADMAP_MAKE_TARGET="roadmap-acceptance-validate-output"' in content
    assert 'run_roadmap_make_target "$ROADMAP_MAKE_TARGET" "$@"' in content
