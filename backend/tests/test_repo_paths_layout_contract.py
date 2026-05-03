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


def test_dockerignore_trims_build_context() -> None:
    """根目录 .dockerignore 须排除 .git、node_modules、.env*，避免镜像构建拖入大目录或密钥。"""
    root = repo_root()
    path = root / ".dockerignore"
    assert path.is_file(), "expected repo-root .dockerignore (docker build context from .)"
    text = path.read_text(encoding="utf-8")
    assert ".git" in text
    assert "node_modules" in text
    assert ".env" in text
