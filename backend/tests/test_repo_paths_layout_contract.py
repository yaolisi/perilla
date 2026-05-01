"""Sanity checks for ``tests.repo_paths`` layout detection."""

from __future__ import annotations

import pytest

from tests.repo_paths import (
    is_standalone_backend_layout,
    monorepo_contract_layout_available,
    repo_path,
    repo_root,
)

pytestmark = pytest.mark.requires_monorepo


def test_repo_paths_points_at_monorepo_root_with_makefile_and_backend_scripts() -> None:
    assert monorepo_contract_layout_available()
    assert not is_standalone_backend_layout()
    root = repo_root()
    assert (root / "Makefile").is_file()
    assert repo_path("backend/scripts").is_dir()
