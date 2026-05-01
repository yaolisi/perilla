"""
智能体 API 集成测试：execution_strategy / model_params 冲突、enabled_skills_meta（GET 列表/单条、POST 创建）。

使用 dependency_overrides 注入 admin 角色；内存 registry + SkillRegistry / ModelRegistry stub，避免真实 DB。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class _FakeSkill:
    """SkillRegistry stub：必须提供 `to_dict()`（`_enabled_skills_meta` 依赖）。"""

    def __init__(self, skill_id: str) -> None:
        self.id = skill_id

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.id.replace("builtin_", "", 1), "is_mcp": False}


class _FakeSkillReg:
    @classmethod
    def get(cls, skill_id: str, version=None):
        return _FakeSkill(skill_id)


class _StubModel:
    __slots__ = ("id",)

    def __init__(self, mid: str) -> None:
        self.id = mid


class _FakeModelRegistry:
    """create_agent 会校验 model_id；仅承认 stub-model。"""

    def get_model(self, model_id: str):
        if model_id == "stub-model":
            return _StubModel(model_id)
        return None

    def list_models(self):
        return [_StubModel("stub-model")]


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.agents import router as agents_router
from core.agent_runtime.definition import AgentDefinition
from core.security.deps import require_authenticated_platform_admin
from core.security.rbac import PlatformRole

from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.no_fallback


class _MemRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentDefinition] = {}

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self._agents.get(agent_id)

    def update_agent(self, agent: AgentDefinition) -> bool:
        self._agents[agent.agent_id] = agent
        return True

    def create_agent(self, agent: AgentDefinition) -> bool:
        self._agents[agent.agent_id] = agent
        return True

    def list_agents(self):
        return list(self._agents.values())


@pytest.fixture()
def mem_registry(monkeypatch) -> _MemRegistry:
    reg = _MemRegistry()
    monkeypatch.setattr("api.agents.get_agent_registry", lambda: reg)

    monkeypatch.setattr("api.agents.SkillRegistry", _FakeSkillReg)

    def _no_blocked(skills):
        return []

    monkeypatch.setattr("api.agents.get_blocked_skills", _no_blocked)

    monkeypatch.setattr("api.agents.get_model_registry", lambda: _FakeModelRegistry())

    return reg


@pytest.fixture()
def agents_client_auth_only(mem_registry: _MemRegistry) -> TestClient:
    """走真实鉴权依赖（不使用 dependency_overrides），用于 401/403。"""
    return TestClient(make_fastapi_app_router_only(agents_router))


@pytest.fixture()
def agents_client(mem_registry: _MemRegistry, monkeypatch) -> TestClient:
    app = make_fastapi_app_router_only(agents_router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: PlatformRole.ADMIN

    seed = AgentDefinition(
        agent_id="agent_kernel_e2e",
        name="Seed",
        description="",
        model_id="stub-model",
        system_prompt="",
        enabled_skills=["builtin_stub.skill"],
        execution_mode="plan_based",
        model_params={"legacy_param": True},
    )
    mem_registry._agents[seed.agent_id] = seed

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _put_payload(**kwargs: Any) -> Dict[str, Any]:
    base = {
        "name": "Updated",
        "description": "",
        "model_id": "stub-model",
        "system_prompt": "",
        "enabled_skills": ["builtin_stub.skill"],
        "rag_ids": [],
        "max_steps": 10,
        "temperature": 0.7,
        "execution_mode": "plan_based",
        "use_execution_kernel": None,
        "max_replan_count": 3,
        "on_failure_strategy": "stop",
        "replan_prompt": "",
        "model_params": {},
    }
    base.update(kwargs)
    return base


def test_put_agent_returns_400_when_execution_strategy_conflicts(
    agents_client: TestClient,
    fallback_probe,
):
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(
            execution_strategy="serial",
            model_params={"execution_strategy": "parallel_kernel"},
        ),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "agent_kernel_opts_execution_strategy_conflict"
    assert "kernel options conflict" in body.get("detail", "")
    assert fallback_probe == []


def test_put_agent_returns_400_when_model_params_rag_invalid(
    agents_client: TestClient,
):
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(model_params={"rag_top_k": 0}),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "agent_invalid_model_params_rag"
    assert body.get("error", {}).get("details", {}).get("field") == "model_params.rag_top_k"


def test_put_agent_returns_503_when_kb_store_unavailable_with_rag_ids(
    agents_client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr("api.agents.get_kb_store", lambda: None)
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(rag_ids=["kb_any"]),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 503
    assert resp.json().get("error", {}).get("code") == "agent_kb_store_unavailable"


def test_post_create_agent_returns_400_when_model_params_rag_invalid(
    agents_client: TestClient,
):
    resp = agents_client.post(
        "/api/agents",
        json={
            "name": "Bad RAG Params",
            "description": "",
            "model_id": "stub-model",
            "system_prompt": "",
            "enabled_skills": ["builtin_create.skill"],
            "rag_ids": [],
            "max_steps": 10,
            "temperature": 0.7,
            "execution_mode": "legacy",
            "model_params": {"rag_min_relevance_score": 2},
        },
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "agent_invalid_model_params_rag"
    assert body.get("error", {}).get("details", {}).get("field") == "model_params.rag_min_relevance_score"


def test_put_agent_returns_400_when_max_parallel_conflicts(
    agents_client: TestClient,
):
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(
            max_parallel_nodes=2,
            model_params={"max_parallel_nodes": 5},
        ),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error", {}).get("code") == "agent_kernel_opts_max_parallel_conflict"
    assert "kernel options conflict" in body.get("detail", "")


def test_get_agent_includes_enabled_skills_meta(agents_client: TestClient):
    r = agents_client.get(
        "/api/agents/agent_kernel_e2e",
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("enabled_skills") == ["builtin_stub.skill"]
    assert j.get("enabled_skills_meta") == [
        {
            "id": "builtin_stub.skill",
            "name": "stub.skill",
            "is_mcp": False,
        }
    ]


def test_list_agents_includes_enabled_skills_meta(agents_client: TestClient):
    r = agents_client.get(
        "/api/agents",
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("object") == "list"
    data = j.get("data") or []
    assert len(data) == 1
    a0 = data[0]
    assert a0.get("agent_id") == "agent_kernel_e2e"
    assert a0.get("enabled_skills") == ["builtin_stub.skill"]
    assert a0.get("enabled_skills_meta") == [
        {
            "id": "builtin_stub.skill",
            "name": "stub.skill",
            "is_mcp": False,
        }
    ]


def test_post_create_agent_returns_enabled_skills_meta(
    agents_client: TestClient,
    mem_registry: _MemRegistry,
):
    before = len(mem_registry.list_agents())
    resp = agents_client.post(
        "/api/agents",
        json={
            "name": "Created Via API",
            "description": "",
            "model_id": "stub-model",
            "system_prompt": "",
            "enabled_skills": ["builtin_create.skill"],
            "rag_ids": [],
            "max_steps": 10,
            "temperature": 0.7,
            "execution_mode": "legacy",
        },
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j.get("name") == "Created Via API"
    assert j.get("model_id") == "stub-model"
    assert j.get("enabled_skills") == ["builtin_create.skill"]
    assert j.get("enabled_skills_meta") == [
        {
            "id": "builtin_create.skill",
            "name": "create.skill",
            "is_mcp": False,
        }
    ]
    aid = j.get("agent_id")
    assert isinstance(aid, str) and aid.startswith("agent_")
    assert mem_registry.get_agent(aid) is not None
    assert len(mem_registry.list_agents()) == before + 1


def test_put_agent_response_enabled_skills_meta_matches_list_order(
    mem_registry: _MemRegistry,
    agents_client: TestClient,
):
    """更新 enabled_skills 时，响应中 meta 与列表同序、与 SkillRegistry 展示名一致。"""
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(
            enabled_skills=["builtin_zebra.skill", "builtin_apple.skill"],
        ),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("enabled_skills") == ["builtin_zebra.skill", "builtin_apple.skill"]
    assert data.get("enabled_skills_meta") == [
        {"id": "builtin_zebra.skill", "name": "zebra.skill", "is_mcp": False},
        {"id": "builtin_apple.skill", "name": "apple.skill", "is_mcp": False},
    ]
    stored = mem_registry.get_agent("agent_kernel_e2e")
    assert stored is not None
    assert list(stored.enabled_skills) == ["builtin_zebra.skill", "builtin_apple.skill"]
    # 恢复 seed，避免影响后续用例或单独挑选运行时的顺序依赖
    restore = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert restore.status_code == 200


def test_put_agent_ok_when_kernel_fields_aligned(mem_registry: _MemRegistry, agents_client: TestClient):
    resp = agents_client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(
            execution_strategy="parallel_kernel",
            max_parallel_nodes=4,
            model_params={
                "execution_strategy": "parallel_kernel",
                "max_parallel_nodes": 4,
            },
        ),
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("execution_strategy") == "parallel_kernel"
    assert data.get("max_parallel_nodes") == 4
    assert data.get("enabled_skills_meta") == [
        {
            "id": "builtin_stub.skill",
            "name": "stub.skill",
            "is_mcp": False,
        }
    ]
    stored = mem_registry.get_agent("agent_kernel_e2e")
    assert stored is not None
    assert stored.execution_strategy == "parallel_kernel"
    assert stored.max_parallel_nodes == 4


def test_put_agent_401_when_api_key_missing(
    agents_client_auth_only: TestClient,
):
    resp = agents_client_auth_only.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(),
    )
    assert resp.status_code == 401
    detail = resp.json().get("detail", "")
    assert "missing API key" in detail
    assert "X-Api-Key" in detail


def test_put_agent_403_when_role_not_admin(
    agents_client_auth_only: TestClient,
):
    """未设置 platform_role 时 get_platform_role 默认为 OPERATOR → 非 admin。"""
    resp = agents_client_auth_only.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(),
        headers={"X-Api-Key": "operator-or-any-key"},
    )
    assert resp.status_code == 403
    assert resp.json().get("detail") == "platform admin access denied"


def test_put_agent_403_when_role_viewer_via_middleware(
    mem_registry: _MemRegistry,
):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request

    class _InjectRole(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request.state.platform_role = PlatformRole.VIEWER
            return await call_next(request)

    app = FastAPI()
    app.add_middleware(_InjectRole)
    app.include_router(agents_router)
    client = TestClient(app)

    resp = client.put(
        "/api/agents/agent_kernel_e2e",
        json=_put_payload(),
        headers={"X-Api-Key": "viewer-key"},
    )
    assert resp.status_code == 403
    assert resp.json().get("detail") == "platform admin access denied"


def test_run_agent_not_found_returns_structured_error(agents_client: TestClient):
    resp = agents_client.post(
        "/api/agents/agent_not_exists/run",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers={"X-Api-Key": "dummy-admin-key"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "agent not found"
    assert body.get("error", {}).get("code") == "agent_not_found"
