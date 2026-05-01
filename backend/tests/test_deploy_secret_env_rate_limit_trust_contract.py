"""Secret 示例须保留 API_RATE_LIMIT_TRUST_X_FORWARDED_FOR 运维提示（防误删）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_secret_env_example_documents_rate_limit_trust_x_forwarded_for() -> None:
    p = repo_path("deploy/k8s/secret-env.example.yaml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "API_RATE_LIMIT_TRUST_X_FORWARDED_FOR" in text
    assert "X-Forwarded-For" in text
