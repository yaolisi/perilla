"""
Skills 控制面 execute：租户经 resolve_api_tenant_id 进入 SkillExecutionRequest。

中间件将 X-Tenant-Id 写入 request.state（与 MCP 集成测约定一致）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api import skills as skills_api
from core.security.deps import require_authenticated_platform_admin
from core.skills.contract import SkillExecutionResponse
from core.skills.models import Skill
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.tenant_isolation

_SKILL_ID = "skill_tenant_exec_probe"


def _dummy_skill() -> Skill:
    now = datetime.now(UTC)
    return Skill(
        id=_SKILL_ID,
        name="Tenant Probe",
        description="",
        category="",
        type="prompt",
        definition={},
        input_schema={"type": "object"},
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def _client() -> TestClient:
    app = make_fastapi_app_router_only(skills_api)

    @app.middleware("http")
    async def _trusted_tenant_from_gateway(request: Request, call_next):  # type: ignore[no-untyped-def]
        hdr = (request.headers.get("X-Tenant-Id") or "").strip()
        request.state.tenant_id = hdr if hdr else None
        return await call_next(request)

    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_skills_execute_passes_resolved_tenant_id_to_execution_request() -> None:
    captured: dict[str, object] = {}

    async def _capture_execute(*args):  # noqa: ANN002
        # classmethod 经 patch 后可能只收到 (request,)
        request = args[-1]
        captured["tenant_id"] = request.tenant_id
        return SkillExecutionResponse.success({"probe": True})

    client = _client()
    with (
        patch.object(skills_api.SkillExecutor, "execute", new=_capture_execute),
        patch.object(skills_api, "get_skill", return_value=_dummy_skill()),
        patch.object(skills_api, "get_blocked_skills", return_value=[]),
    ):
        resp = client.post(
            f"/api/skills/{_SKILL_ID}/execute",
            headers={"X-Tenant-Id": "tenant_skill_exec"},
            json={"inputs": {}},
        )

    assert resp.status_code == 200
    assert resp.json().get("type") == "success"
    assert captured.get("tenant_id") == "tenant_skill_exec"


def test_skills_execute_default_tenant_when_no_header() -> None:
    captured: dict[str, object] = {}

    async def _capture_execute(*args):  # noqa: ANN002
        request = args[-1]
        captured["tenant_id"] = request.tenant_id
        return SkillExecutionResponse.success({"probe": True})

    client = _client()
    with (
        patch.object(skills_api.SkillExecutor, "execute", new=_capture_execute),
        patch.object(skills_api, "get_skill", return_value=_dummy_skill()),
        patch.object(skills_api, "get_blocked_skills", return_value=[]),
    ):
        resp = client.post(
            f"/api/skills/{_SKILL_ID}/execute",
            json={"inputs": {}},
        )

    assert resp.status_code == 200
    tid = captured.get("tenant_id")
    assert isinstance(tid, str)
    assert tid == "default"
