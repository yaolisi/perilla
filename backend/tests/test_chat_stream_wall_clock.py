"""Chat SSE 墙钟上限：本地 agent 打桩，不连真实模型。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from core.types import Message
from middleware.csrf_protection import CSRFMiddleware
from middleware.user_context import UserContextMiddleware
from tests.helpers import make_fastapi_app_router_only
from tests.helpers.chat_stream_helpers import chat_prime_csrf


@pytest.fixture()
def chat_wall_clock_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from api import chat as chat_api

    prev_persist = getattr(settings, "chat_persistence_mode", "full")
    prev_resume = bool(getattr(settings, "chat_stream_resume_enabled", True))
    prev_wall = int(getattr(settings, "chat_stream_wall_clock_max_seconds", 0) or 0)
    prev_csrf = bool(getattr(settings, "csrf_enabled", True))
    settings.chat_persistence_mode = "off"
    settings.chat_stream_resume_enabled = False
    settings.chat_stream_wall_clock_max_seconds = 1
    settings.csrf_enabled = True
    settings.csrf_cookie_name = "csrf_token"
    settings.csrf_header_name = "X-CSRF-Token"

    class _Agent:
        async def stream_chat(self, req: Any) -> Any:
            yield "a"
            await asyncio.sleep(2.0)
            yield "b"

    class _Router:
        def get_agent(self, model_id: str) -> _Agent:
            return _Agent()

    def _uid(_request: Any) -> str:
        return "wall-clock-user"

    def _resolve(_req: Any, _request: Any, _user_id: str) -> str:
        return "dummy-model"

    umsg = Message(role="user", content="hello")
    st = ("hello", None, "off", umsg, False, None, False)

    def _prep_state(*_a: Any, **_k: Any) -> Any:
        return st

    async def _prep_ctx(*_a: Any, **_k: Any) -> Any:
        return (None, 0, None)

    monkeypatch.setattr(chat_api, "get_router", lambda: _Router())
    monkeypatch.setattr(chat_api, "_get_user_id", _uid)
    monkeypatch.setattr(chat_api, "_resolve_model_for_request", _resolve)
    monkeypatch.setattr(chat_api, "_prepare_chat_request_state", _prep_state)
    monkeypatch.setattr(chat_api, "_prepare_chat_runtime_context", _prep_ctx)

    app = make_fastapi_app_router_only(chat_api)
    app.add_middleware(UserContextMiddleware)
    app.add_middleware(CSRFMiddleware)

    @app.get("/_ping")
    def _ping() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    try:
        yield client
    finally:
        settings.chat_persistence_mode = prev_persist
        settings.chat_stream_resume_enabled = prev_resume
        settings.chat_stream_wall_clock_max_seconds = prev_wall
        settings.csrf_enabled = prev_csrf


def test_stream_wall_clock_limit_stops_before_second_token(chat_wall_clock_client: TestClient) -> None:
    client = chat_wall_clock_client
    token = chat_prime_csrf(client)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
        headers={"X-User-Id": "wall-clock-user", "X-CSRF-Token": token},
    )
    assert r.status_code == 200
    body = r.text or ""
    assert "a" in body
    assert '"delta": {"content": "b"}' not in body
    assert "wall clock" in body.lower()
