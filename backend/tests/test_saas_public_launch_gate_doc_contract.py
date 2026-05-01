"""公网 SaaS 多租户上线门禁文档须存在且保留关键锚点（防误删）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_DOC = "docs/ops/SAAS_PUBLIC_LAUNCH_GATE_ZH.md"


def test_saas_public_launch_gate_doc_exists_and_has_gate_anchors() -> None:
    p = repo_path(_DOC)
    assert p.is_file(), f"missing {_DOC}"
    text = p.read_text(encoding="utf-8")
    for needle in (
        "P0",
        "P1",
        "多租户",
        "validate_production_security_guardrails",
        "apply_production_security_defaults",
        "TRUSTED_HOSTS",
        "RBAC_DEFAULT_ROLE",
        "SECURITY_GUARDRAILS_STRICT",
        "docker-compose.prod.yml",
        "deploy/helm/perilla-backend",
        "middleware/tenant_paths.py",
    ):
        assert needle in text, f"{_DOC} must contain {needle!r}"
