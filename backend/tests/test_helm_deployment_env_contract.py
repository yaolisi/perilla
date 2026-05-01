"""Helm deployment 模板须包含与 Settings 对齐的 env 块名（防 template 漂移）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_helm_deployment_templates_extended_pool_inference_local_csrf_env_names() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/deployment.yaml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    for upper in (
        "DB_POOL_RECYCLE_SECONDS",
        "INFERENCE_CACHE_ENABLED",
        "LOCAL_MODEL_DIRECTORY",
        "AUTO_UNLOAD_LOCAL_MODEL_ON_SWITCH",
        "CSRF_HEADER_NAME",
        "CSRF_COOKIE_NAME",
        "CSRF_COOKIE_PATH",
        "CSRF_COOKIE_SAMESITE",
        "CSRF_COOKIE_MAX_AGE_SECONDS",
    ):
        assert f"- name: {upper}" in text, f"missing deployment env block: {upper}"
