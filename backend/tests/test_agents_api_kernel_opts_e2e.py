"""
PUT /api/agents/{id} 对 execution_strategy / model_params 冲突的集成测试。

使用 dependency_overrides 注入 admin 角色；内存 registry + SkillRegistry stub，避免真实 DB。
"""

from __future__ import annotations

import types
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.agents import router as agents_router
from api.errors import register_error_handlers
from core.agent_runtime.definition import AgentDefinition
from core.security.deps import require_authenticated_platform_admin
from core.security.rbac import PlatformRole


class _MemRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentDefinition] = {}

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self._agents.get(agent_id)

    def update_agent(self, agent: AgentDefinition) -> bool:
        self._agents[agent.agent_id] = agent
        return True

    def list_agents(self):
        return list(self._agents.values())


@pytest.fixture()
def mem_registry(monkeypatch) -> _MemRegistry:
    reg = _MemRegistry()
    monkeypatch.setattr("api.agents.get_agent_registry", lambda: reg)

    class _FakeSkillReg:
        @classmethod
        def get(cls, skill_id: str, version=None):
            return types.SimpleNamespace(id=skill_id)

    monkeypatch.setattr("api.agents.SkillRegistry", _FakeSkillReg)

    def _no_blocked(skills):
        return []

    monkeypatch.setattr("api.agents.get_blocked_skills", _no_blocked)

    return reg


@pytest.fixture()
def agents_client_auth_only(mem_registry: _MemRegistry) -> TestClient:
    """走真实鉴权依赖（不使用 dependency_overrides），用于 401/403。"""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(agents_router)
    return TestClient(app)


@pytest.fixture()
def agents_client(mem_registry: _MemRegistry, monkeypatch) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(agents_router)
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


@pytest.mark.no_fallback
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
    assert "execution_strategy conflicts" in resp.json().get("detail", "")
    assert fallback_probe == []


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
    assert "max_parallel_nodes conflicts" in resp.json().get("detail", "")


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
    assert body.get("detail") == "Agent not found"
    assert body.get("error", {}).get("code") == "agent_not_found"
