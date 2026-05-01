from __future__ import annotations

import asyncio
from typing import Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.agents import router as agents_router
from api.agents import session_router as agent_sessions_router
from api.errors import register_error_handlers
from core.agent_runtime.definition import AgentDefinition
from core.agent_runtime.session import AgentSession
from core.security.deps import require_authenticated_platform_admin
from core.security.rbac import PlatformRole
from core.types import Message
from tests.idempotency_testkit import (
    DummyDb,
    FakeClaim,
    build_fixed_idempotency_service,
    build_keyed_hash_idempotency_service,
)

ADMIN_API_KEY = "dummy-admin-key"


def _run_headers(*, idem_key: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, str]:
    headers: Dict[str, str] = {"X-Api-Key": ADMIN_API_KEY}
    if user_id:
        headers["X-User-Id"] = user_id
    if idem_key:
        headers["Idempotency-Key"] = idem_key
    return headers


def _run_payload(content: str = "hello", *, session_id: Optional[str] = None) -> Dict[str, object]:
    payload: Dict[str, object] = {"messages": [{"role": "user", "content": content}]}
    if session_id:
        payload["session_id"] = session_id
    return payload


class _MemRegistry:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentDefinition] = {}

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        return self._agents.get(agent_id)


class _MemSessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, AgentSession] = {}

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)

    def save_session(self, session: AgentSession) -> bool:
        self._sessions[session.session_id] = session
        return True

    def list_sessions(
        self,
        user_id: str = "default",
        limit: int = 50,
        agent_id: Optional[str] = None,
    ):
        out = [s for s in self._sessions.values() if s.user_id == user_id]
        if agent_id:
            out = [s for s in out if s.agent_id == agent_id]
        return out[:limit]


@pytest.fixture()
def agent_run_client(monkeypatch) -> TestClient:
    registry = _MemRegistry()
    store = _MemSessionStore()

    registry._agents["agent_run_1"] = AgentDefinition(
        agent_id="agent_run_1",
        name="Runner",
        description="",
        model_id="stub-model",
        system_prompt="",
        enabled_skills=[],
        execution_mode="plan_based",
        model_params={},
    )

    class _Runtime:
        async def run(self, agent, session, workspace=None):
            await asyncio.sleep(0)
            session.status = "finished"
            session.messages.append(Message(role="assistant", content="done"))
            store.save_session(session)
            return session

    monkeypatch.setattr("api.agents.get_agent_registry", lambda: registry)
    monkeypatch.setattr("api.agents.get_agent_session_store", lambda: store)
    monkeypatch.setattr("api.agents.get_agent_executor", lambda: object())
    monkeypatch.setattr("api.agents.get_agent_runtime", lambda _executor: _Runtime())

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(agents_router)
    app.include_router(agent_sessions_router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: PlatformRole.ADMIN

    client = TestClient(app)
    client._test_session_store = store  # type: ignore[attr-defined]
    return client


@pytest.mark.no_fallback
def test_run_agent_then_fetch_session(agent_run_client: TestClient, fallback_probe):
    headers = _run_headers(user_id="u1")
    run_resp = agent_run_client.post(
        "/api/agents/agent_run_1/run",
        json=_run_payload("hello", session_id="asess_flow_1"),
        headers=headers,
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["session_id"] == "asess_flow_1"
    assert run_data["status"] == "finished"
    assert run_data["messages"][-1]["role"] == "assistant"
    assert run_data["messages"][-1]["content"] == "done"

    session_resp = agent_run_client.get("/api/agent-sessions/asess_flow_1", headers=headers)
    assert session_resp.status_code == 200
    session_data = session_resp.json()
    assert session_data["session_id"] == "asess_flow_1"
    assert session_data["status"] == "finished"
    assert session_data["messages"][-1]["content"] == "done"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_run_agent_not_found_returns_structured_error(agent_run_client: TestClient, fallback_probe):
    resp = agent_run_client.post(
        "/api/agents/agent_missing/run",
        json=_run_payload("hello"),
        headers=_run_headers(),
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body.get("detail") == "agent not found"
    assert body.get("error", {}).get("code") == "agent_not_found"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_run_agent_idempotency_conflict_returns_structured_error(
    agent_run_client: TestClient,
    monkeypatch,
    fallback_probe,
):
    monkeypatch.setattr(
        "api.agents.IdempotencyService",
        build_fixed_idempotency_service(FakeClaim(conflict=True, is_new=False, record_id=1)),
    )
    monkeypatch.setattr("api.agents.SessionLocal", lambda: DummyDb())

    resp = agent_run_client.post(
        "/api/agents/agent_run_1/run",
        json=_run_payload("hello"),
        headers=_run_headers(idem_key="idem-agent-conflict"),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_conflict"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_run_agent_idempotency_hit_returns_existing_session(
    agent_run_client: TestClient,
    monkeypatch,
    fallback_probe,
):
    store = agent_run_client._test_session_store  # type: ignore[attr-defined]
    store.save_session(
        AgentSession(
            session_id="asess_idem_hit_1",
            agent_id="agent_run_1",
            user_id="default",
            status="finished",
            messages=[
                Message(role="user", content="hello"),
                Message(role="assistant", content="cached"),
            ],
        )
    )

    monkeypatch.setattr(
        "api.agents.IdempotencyService",
        build_fixed_idempotency_service(
            FakeClaim(conflict=False, is_new=False, record_id=2, response_ref="asess_idem_hit_1")
        ),
    )
    monkeypatch.setattr("api.agents.SessionLocal", lambda: DummyDb())

    resp = agent_run_client.post(
        "/api/agents/agent_run_1/run",
        json=_run_payload("hello"),
        headers=_run_headers(idem_key="idem-agent-hit"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("session_id") == "asess_idem_hit_1"
    assert body.get("messages", [])[-1].get("content") == "cached"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_run_agent_idempotency_in_progress_returns_structured_error(
    agent_run_client: TestClient,
    monkeypatch,
    fallback_probe,
):
    monkeypatch.setattr(
        "api.agents.IdempotencyService",
        build_fixed_idempotency_service(FakeClaim(conflict=False, is_new=False, record_id=3)),
    )
    monkeypatch.setattr("api.agents.SessionLocal", lambda: DummyDb())

    resp = agent_run_client.post(
        "/api/agents/agent_run_1/run",
        json=_run_payload("hello"),
        headers=_run_headers(idem_key="idem-agent-in-progress"),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body.get("error", {}).get("code") == "idempotency_in_progress"
    assert fallback_probe == []


@pytest.mark.no_fallback
def test_run_agent_same_key_different_payload_returns_conflict(
    agent_run_client: TestClient,
    monkeypatch,
    fallback_probe,
):
    monkeypatch.setattr(
        "api.agents.IdempotencyService",
        build_keyed_hash_idempotency_service(record_id=10),
    )
    monkeypatch.setattr("api.agents.SessionLocal", lambda: DummyDb())

    headers = _run_headers(user_id="u1", idem_key="idem-agent-hash-mismatch")
    payload_a = _run_payload("hello")
    payload_b = _run_payload("hello changed")

    resp_a = agent_run_client.post("/api/agents/agent_run_1/run", json=payload_a, headers=headers)
    assert resp_a.status_code == 200
    resp_b = agent_run_client.post("/api/agents/agent_run_1/run", json=payload_b, headers=headers)
    assert resp_b.status_code == 409
    body = resp_b.json()
    assert body.get("error", {}).get("code") == "idempotency_conflict"
    assert fallback_probe == []
