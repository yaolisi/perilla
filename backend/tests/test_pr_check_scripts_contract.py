from __future__ import annotations

from pathlib import Path

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def _read_script(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pr_check_scripts_support_roadmap_acceptance_flags() -> None:
    root = repo_root()
    pr_check = _read_script(root / "scripts" / "pr-check.sh")
    pr_check_fast = _read_script(root / "scripts" / "pr-check-fast.sh")

    assert "--with-roadmap-acceptance" in pr_check
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check
    assert "--skip-roadmap-acceptance" in pr_check
    assert "--with-roadmap-acceptance" in pr_check_fast
    assert "SKIP_ROADMAP_ACCEPTANCE_IN_PR_CHECK=0" in pr_check_fast
    assert "--skip-roadmap-acceptance" in pr_check_fast
