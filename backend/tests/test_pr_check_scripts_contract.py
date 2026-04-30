from __future__ import annotations

from pathlib import Path


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pr_check_scripts_support_with_roadmap_acceptance_flag() -> None:
    root = Path(__file__).resolve().parents[2]
    pr_check = _read_script(root / "scripts" / "pr-check.sh")
    pr_check_fast = _read_script(root / "scripts" / "pr-check-fast.sh")

    assert "--with-roadmap-acceptance" in pr_check
    assert "ROADMAP_ACCEPTANCE_IN_PR_CHECK=1" in pr_check
    assert "--with-roadmap-acceptance" in pr_check_fast
    assert "ROADMAP_ACCEPTANCE_IN_PR_CHECK=1" in pr_check_fast
