"""POST /v1/chat/completions 流式：stream_gzip / stream_format（打桩 agent，不连真实模型）。"""

from __future__ import annotations

import gzip
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
def chat_stream_client_mock(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from api import chat as chat_api

    prev_persist = getattr(settings, "chat_persistence_mode", "full")
    prev_resume = bool(getattr(settings, "chat_stream_resume_enabled", True))
    prev_csrf = bool(getattr(settings, "csrf_enabled", True))
    settings.chat_persistence_mode = "off"
    settings.chat_stream_resume_enabled = False
    settings.csrf_enabled = True
    settings.csrf_cookie_name = "csrf_token"
    settings.csrf_header_name = "X-CSRF-Token"

    class _Agent:
        async def stream_chat(self, req: Any) -> Any:
            yield "Zz"

    class _Router:
        def get_agent(self, model_id: str) -> _Agent:
            return _Agent()

    def _uid(_request: Any) -> str:
        return "gzip-test-user"

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
        settings.csrf_enabled = prev_csrf


def _sse_text(resp: Any) -> str:
    """
    合并 TestClient/httpx 的两种行为：可能保留 gzip 头并自动解压 .content，也可能保留原始压缩字节。
    仅当内容仍以 gzip 魔数开头时才手动解压。
    """
    raw: bytes = resp.content
    if len(raw) >= 2 and raw[0:2] == b"\x1f\x8b":
        return gzip.decompress(raw).decode("utf-8")
    return (resp.text or raw.decode("utf-8", errors="replace") or "")


def test_stream_gzip_response_has_gzip_and_payload(chat_stream_client_mock: TestClient) -> None:
    client = chat_stream_client_mock
    token = chat_prime_csrf(client)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_gzip": True,
        },
        headers={"X-User-Id": "gzip-test-user", "X-CSRF-Token": token},
    )
    assert r.status_code == 200, r.text
    body = _sse_text(r)
    assert "Zz" in body
    assert "data:" in body
    # 服务端对流式体显式设了 gzip；客户端可能仍带 content-encoding 头、body 已解压
    enc_h = (r.headers.get("content-encoding") or "").lower()
    raw_b: bytes = r.content
    has_gzip_header = "gzip" in enc_h
    has_gzip_bytes = len(raw_b) >= 2 and raw_b[0:2] == b"\x1f\x8b"
    assert has_gzip_header or has_gzip_bytes, (
        f"expected gzip marker; encoding={r.headers.get('content-encoding')!r}, head={raw_b[:4]!r}"
    )


def test_stream_without_gzip_no_gzip_marker(chat_stream_client_mock: TestClient) -> None:
    """stream_gzip 默认/显式 false：SSE 明文，不应带 gzip 压缩标记。"""
    client = chat_stream_client_mock
    token = chat_prime_csrf(client)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_gzip": False,
        },
        headers={"X-User-Id": "gzip-test-user", "X-CSRF-Token": token},
    )
    assert r.status_code == 200, r.text
    body = _sse_text(r)
    assert "Zz" in body
    assert "data:" in body
    enc_h = (r.headers.get("content-encoding") or "").lower()
    raw_b: bytes = r.content
    assert "gzip" not in enc_h, f"unexpected content-encoding: {r.headers.get('content-encoding')!r}"
    assert not (len(raw_b) >= 2 and raw_b[0:2] == b"\x1f\x8b"), "body should not be raw gzip"
    # 未压缩时 wire 上应以 SSE 的 data: 或解压后的 text 以 data: 开头
    assert body.lstrip().startswith("data:") or raw_b[:5] == b"data:"


def test_stream_format_jsonl_perilla_payload(chat_stream_client_mock: TestClient) -> None:
    client = chat_stream_client_mock
    token = chat_prime_csrf(client)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_format": "jsonl",
            "stream_gzip": False,
        },
        headers={"X-User-Id": "gzip-test-user", "X-CSRF-Token": token},
    )
    assert r.status_code == 200, r.text
    body = _sse_text(r)
    assert "perilla.stream.jsonl" in body
    assert "Zz" in body
    assert "chat.completion.chunk" not in body


def test_stream_format_markdown_perilla_payload(chat_stream_client_mock: TestClient) -> None:
    client = chat_stream_client_mock
    token = chat_prime_csrf(client)
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "stream_format": "markdown",
            "stream_gzip": False,
        },
        headers={"X-User-Id": "gzip-test-user", "X-CSRF-Token": token},
    )
    assert r.status_code == 200, r.text
    body = _sse_text(r)
    assert "perilla.stream.md" in body
    assert "Zz" in body
    assert "chat.completion.chunk" not in body
