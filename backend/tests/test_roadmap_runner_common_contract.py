from __future__ import annotations

from pathlib import Path


def test_roadmap_runner_common_keeps_exit_code_hint_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "acceptance" / "roadmap_runner_common.sh"
    content = script.read_text(encoding="utf-8")

    assert "run_roadmap_make_target()" in content
    assert 'ROADMAP_GATE_LOG_PREFIX="${ROADMAP_GATE_LOG_PREFIX:-[roadmap-gate]}"' in content
    assert 'echo "${ROADMAP_GATE_LOG_PREFIX} ${target} failed (exit=${status})" >&2' in content
    assert 'echo "${ROADMAP_GATE_LOG_PREFIX} hint: exit=2 means parameter/input error; exit=1 means contract/business validation failure" >&2' in content
    assert "exit=2 means parameter/input error" in content
    assert "exit=1 means contract/business validation failure" in content
