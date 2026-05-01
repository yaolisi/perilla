"""后端镜像须非 root、监听 8000，与 Helm values / Compose 一致。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo


def test_backend_dockerfile_non_root_uid_1000_and_expose_8000() -> None:
    raw = repo_path("docker/backend.Dockerfile").read_text(encoding="utf-8")
    assert "--uid 1000" in raw
    assert "USER appuser" in raw
    assert "EXPOSE 8000" in raw
