from __future__ import annotations

from fastapi.testclient import TestClient

from api import collaboration as collaboration_api

from tests.helpers import make_fastapi_app_router_only
from core.agent_runtime.collaboration import STATE_KEY_COLLABORATION, STATE_KEY_COLLABORATION_MESSAGES
from core.agent_runtime.session import AgentSession


class _FakeStore:
    def __init__(self, session: AgentSession):
        self._session = session

    def get_session(self, session_id: str):
        if session_id == self._session.session_id:
            return self._session
        return None

    def save_session(self, session: AgentSession) -> bool:
        self._session = session
        return True

    def list_sessions(self, user_id: str = "default", limit: int = 50, agent_id: str | None = None):
        if self._session.user_id != user_id:
            return []
        return [self._session]


def _build_client(fake_store: _FakeStore) -> TestClient:
    app = make_fastapi_app_router_only(collaboration_api)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

    app.dependency_overrides[collaboration_api.require_authenticated_platform_admin] = lambda: None
    collaboration_api.get_agent_session_store = lambda: fake_store  # type: ignore[assignment]
    return TestClient(app)


def test_upsert_collaboration_message_and_replay():
    session = AgentSession(
        session_id="s1",
        agent_id="manager",
        user_id="u1",
        state={STATE_KEY_COLLABORATION: {"correlation_id": "corr-1", "orchestrator_agent_id": "manager"}},
    )
    client = _build_client(_FakeStore(session))

    resp = client.post(
        "/api/collaboration/messages",
        json={
            "correlation_id": "corr-1",
            "session_id": "s1",
            "sender": "manager",
            "receiver": "worker",
            "task_id": "task-1",
            "content": {"action": "collect_data"},
            "status": "running",
        },
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("success") is True
    assert body.get("message", {}).get("task_id") == "task-1"

    replay = client.get("/api/collaboration/correlation/corr-1/messages", headers={"X-User-Id": "u1"})
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body.get("total") == 1
    assert replay_body.get("messages", [])[0]["sender"] == "manager"
    assert replay_body.get("messages", [])[0]["receiver"] == "worker"


def test_upsert_collaboration_message_rejects_correlation_mismatch():
    session = AgentSession(
        session_id="s2",
        agent_id="manager",
        user_id="u2",
        state={
            STATE_KEY_COLLABORATION: {
                "correlation_id": "corr-old",
                "orchestrator_agent_id": "manager",
                STATE_KEY_COLLABORATION_MESSAGES: [],
            }
        },
    )
    client = _build_client(_FakeStore(session))

    resp = client.post(
        "/api/collaboration/messages",
        json={
            "correlation_id": "corr-new",
            "session_id": "s2",
            "sender": "manager",
            "receiver": "worker",
            "task_id": "task-2",
            "content": {"action": "summarize"},
        },
        headers={"X-User-Id": "u2"},
    )
    assert resp.status_code == 400
    assert resp.json().get("error", {}).get("code") == "collaboration_correlation_mismatch"
