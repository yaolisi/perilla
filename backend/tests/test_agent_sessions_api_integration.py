"""
GET/PATCH/DELETE /api/agent-sessions/... 结构化错误响应集成测试。

挂载 session_router + register_error_handlers；内存会话存储，避免真实 DB。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.agents import session_router as agent_sessions_router
from api.errors import register_error_handlers
from core.agent_runtime.session import AgentSession
from core.security.deps import require_authenticated_platform_admin
from core.security.rbac import PlatformRole
from core.tools.sandbox import WorkspacePathError


class _MemSessionStore:
    """最小内存实现，覆盖 agent-sessions 路由所需方法。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, AgentSession] = {}

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)

    def save_session(self, session: AgentSession) -> bool:
        self._sessions[session.session_id] = session
        return True

    def delete_session(self, session_id: str, user_id: str = "default") -> bool:
        s = self._sessions.get(session_id)
        if not s or s.user_id != user_id:
            return False
        del self._sessions[session_id]
        return True

    def delete_message(self, session_id: str, message_index: int) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        if message_index < 0 or message_index >= len(session.messages):
            return False
        session.messages.pop(message_index)
        return self.save_session(session)

    def list_sessions(
        self,
        user_id: str = "default",
        limit: int = 50,
        agent_id: Optional[str] = None,
    ) -> list:
        out = [s for s in self._sessions.values() if s.user_id == user_id]
        if agent_id:
            out = [s for s in out if s.agent_id == agent_id]
        return out[:limit]


HEADERS_ADMIN = {"X-Api-Key": "dummy-admin-key"}


@pytest.fixture()
def sessions_client(monkeypatch) -> TestClient:
    store = _MemSessionStore()
    monkeypatch.setattr("api.agents.get_agent_session_store", lambda: store)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(agent_sessions_router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: PlatformRole.ADMIN

    client = TestClient(app)
    client._test_session_store = store  # type: ignore[attr-defined]
    return client


def _assert_structured(body: dict[str, Any], *, code: str, message_substr: str = "") -> None:
    assert body.get("detail")
    err = body.get("error") or {}
    assert err.get("code") == code
    if message_substr:
        assert message_substr in str(err.get("message", ""))


@pytest.mark.no_fallback
def test_get_agent_session_not_found_returns_structured_error(
    sessions_client: TestClient,
    fallback_probe,
):
    resp = sessions_client.get("/api/agent-sessions/nonexistent-session", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    _assert_structured(body, code="agent_session_not_found")
    assert body["error"]["details"]["session_id"] == "nonexistent-session"
    assert fallback_probe == []


def test_get_agent_session_file_workspace_missing_returns_structured_error(sessions_client: TestClient):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_ws"] = AgentSession(
        session_id="s_ws",
        agent_id="a1",
        user_id="default",
        workspace_dir=None,
    )
    resp = sessions_client.get("/api/agent-sessions/s_ws/files/foo.txt", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    _assert_structured(resp.json(), code="agent_workspace_not_found")


def test_get_agent_session_file_invalid_path_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
    sessions_client: TestClient,
    tmp_path,
):
    ws = tmp_path / "ws"
    ws.mkdir()
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_path"] = AgentSession(
        session_id="s_path",
        agent_id="a1",
        user_id="default",
        workspace_dir=str(ws),
    )
    # ``{filename}`` 只能占一个路径段，真实越界路径无法原样出现在 URL 中；此处注入
    # ``WorkspacePathError`` 仅用于验证 handler 对该异常的结构化映射。
    def _reject(*args: Any, **kwargs: Any):
        raise WorkspacePathError("access denied: outside workspace")

    monkeypatch.setattr("api.agents.resolve_in_workspace", _reject)

    resp = sessions_client.get(
        "/api/agent-sessions/s_path/files/trigger.txt",
        headers=HEADERS_ADMIN,
    )
    assert resp.status_code == 400
    body = resp.json()
    _assert_structured(
        body, code="agent_invalid_workspace_path", message_substr="outside workspace"
    )


def test_get_agent_session_file_missing_returns_structured_error(sessions_client: TestClient, tmp_path):
    ws = tmp_path / "ws2"
    ws.mkdir()
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_file"] = AgentSession(
        session_id="s_file",
        agent_id="a1",
        user_id="default",
        workspace_dir=str(ws),
    )
    resp = sessions_client.get("/api/agent-sessions/s_file/files/missing.bin", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    _assert_structured(body, code="agent_session_file_not_found")
    assert body["error"]["details"]["filename"] == "missing.bin"


def test_patch_agent_session_not_found_returns_structured_error(sessions_client: TestClient):
    resp = sessions_client.patch(
        "/api/agent-sessions/no-such",
        json={"status": "idle"},
        headers=HEADERS_ADMIN,
    )
    assert resp.status_code == 404
    _assert_structured(resp.json(), code="agent_session_not_found")


@pytest.mark.no_fallback
def test_patch_agent_session_save_failed_returns_structured_error(
    sessions_client: TestClient,
    fallback_probe,
):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_save"] = AgentSession(
        session_id="s_save",
        agent_id="a1",
        user_id="default",
    )

    def _fail_save(_session: AgentSession) -> bool:
        return False

    store.save_session = _fail_save  # type: ignore[method-assign]

    resp = sessions_client.patch(
        "/api/agent-sessions/s_save",
        json={"status": "idle"},
        headers=HEADERS_ADMIN,
    )
    assert resp.status_code == 500
    _assert_structured(resp.json(), code="agent_session_save_failed")
    assert fallback_probe == []


def test_delete_agent_session_message_not_found_returns_structured_error(sessions_client: TestClient):
    resp = sessions_client.delete(
        "/api/agent-sessions/unknown_sess/messages/0",
        headers=HEADERS_ADMIN,
    )
    assert resp.status_code == 404
    body = resp.json()
    _assert_structured(body, code="agent_session_message_not_found")
    assert body["error"]["details"]["message_index"] == 0


def test_delete_agent_session_not_found_returns_structured_error(sessions_client: TestClient):
    resp = sessions_client.delete("/api/agent-sessions/ghost", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    _assert_structured(resp.json(), code="agent_session_not_found")


def test_delete_agent_session_wrong_user_returns_not_found(sessions_client: TestClient):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_other"] = AgentSession(
        session_id="s_other",
        agent_id="a1",
        user_id="user-b",
    )
    # 未传 X-User-Id → default，与会话 user_id 不一致 → 删除失败 → 404
    resp = sessions_client.delete("/api/agent-sessions/s_other", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    _assert_structured(resp.json(), code="agent_session_not_found")


def test_stream_agent_session_not_found_returns_structured_error(sessions_client: TestClient):
    resp = sessions_client.get("/api/agent-sessions/nonexistent-session/stream", headers=HEADERS_ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    _assert_structured(body, code="agent_session_not_found")
    assert body["error"]["details"]["session_id"] == "nonexistent-session"


def test_stream_agent_session_idle_emits_status_and_terminal(sessions_client: TestClient):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_stream_idle"] = AgentSession(
        session_id="s_stream_idle",
        agent_id="a1",
        user_id="default",
        status="idle",
    )

    with sessions_client.stream("GET", "/api/agent-sessions/s_stream_idle/stream", headers=HEADERS_ADMIN) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        lines = list(resp.iter_lines())

    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    assert len(data_lines) >= 2
    first_payload = data_lines[0].replace("data: ", "", 1)
    terminal_payload = data_lines[-1].replace("data: ", "", 1)
    first_obj = json.loads(first_payload)
    terminal_obj = json.loads(terminal_payload)

    assert first_obj["type"] == "status"
    assert first_obj["payload"]["session_id"] == "s_stream_idle"
    assert first_obj["payload"]["status"] == "idle"
    assert terminal_obj["type"] == "terminal"
    assert terminal_obj["state"] == "idle"


def test_stream_agent_session_compact_emits_status_delta_and_terminal(sessions_client: TestClient):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    store._sessions["s_stream_compact"] = AgentSession(
        session_id="s_stream_compact",
        agent_id="a1",
        user_id="default",
        status="idle",
        step=3,
    )

    with sessions_client.stream(
        "GET",
        "/api/agent-sessions/s_stream_compact/stream?compact=true",
        headers=HEADERS_ADMIN,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        lines = list(resp.iter_lines())

    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    assert len(data_lines) >= 2
    first_obj = json.loads(data_lines[0].replace("data: ", "", 1))
    terminal_obj = json.loads(data_lines[-1].replace("data: ", "", 1))

    assert first_obj["type"] == "status_delta"
    assert first_obj["payload"]["session_id"] == "s_stream_compact"
    assert first_obj["payload"]["schema_version"] == 1
    assert first_obj["payload"]["status"] == "idle"
    assert first_obj["payload"]["step"] == 3
    assert "messages_count" in first_obj["payload"]
    assert terminal_obj["type"] == "terminal"
    assert terminal_obj["state"] == "idle"


def test_stream_agent_session_runtime_missing_emits_error_code(sessions_client: TestClient):
    store: _MemSessionStore = sessions_client._test_session_store  # type: ignore[assignment]
    session = AgentSession(
        session_id="s_stream_missing_runtime",
        agent_id="a1",
        user_id="default",
        status="running",
    )
    store._sessions[session.session_id] = session

    call_count = 0

    def _flaky_get_session(session_id: str):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return session
        return None

    store.get_session = _flaky_get_session  # type: ignore[method-assign]

    with sessions_client.stream(
        "GET",
        f"/api/agent-sessions/{session.session_id}/stream",
        headers=HEADERS_ADMIN,
    ) as resp:
        assert resp.status_code == 200
        lines = list(resp.iter_lines())

    data_lines = [ln for ln in lines if ln.startswith("data: ")]
    assert data_lines
    first_obj = json.loads(data_lines[0].replace("data: ", "", 1))
    assert first_obj["type"] == "error"
    assert first_obj["error_code"] == "sse_stream_resource_not_found"
