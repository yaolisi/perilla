"""POST /v1/chat/completions/stream/resume 集成测试（CSRF + X-User-Id）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.stream_resume_store import StreamResumeStore
from config.settings import settings
from tests.helpers.chat_stream_helpers import chat_prime_csrf, chat_seed_stream_store


def test_stream_resume_ok_with_csrf_and_x_user_id(chat_stream_resume_client: tuple[TestClient, StreamResumeStore]) -> None:
    client, store = chat_stream_resume_client
    uid = "integration-resume-user-1"
    sid = "resume-integration-sid-0001"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=uid,
        completion_id="chatcmpl-inttest",
        contents=["hello"],
    )

    token = chat_prime_csrf(client)
    resp = client.post(
        "/v1/chat/completions/stream/resume",
        json={"stream_id": sid, "chunk_index": 0},
        headers={
            "X-User-Id": uid,
            "X-CSRF-Token": token,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    body = resp.text
    assert "hello" in body
    assert "[DONE]" in body


def test_stream_resume_wrong_x_user_id_returns_404(chat_stream_resume_client: tuple[TestClient, StreamResumeStore]) -> None:
    client, store = chat_stream_resume_client
    owner = "owner-user-99"
    sid = "resume-integration-sid-0002"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=owner,
        completion_id="chatcmpl-wrong-user",
        contents=["owned-chunk"],
    )

    token = chat_prime_csrf(client)
    resp = client.post(
        "/v1/chat/completions/stream/resume",
        json={"stream_id": sid, "chunk_index": 0},
        headers={
            "X-User-Id": "other-user",
            "X-CSRF-Token": token,
        },
    )
    assert resp.status_code == 404
    err = resp.json()
    assert err.get("error", {}).get("code") == "stream_not_found"


def test_stream_resume_from_middle_chunk_returns_tail_only(
    chat_stream_resume_client: tuple[TestClient, StreamResumeStore],
) -> None:
    client, store = chat_stream_resume_client
    uid = "resume-middle-user"
    sid = "resume-integration-sid-0003"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=uid,
        completion_id="chatcmpl-middle",
        created=1700000001,
        contents=["A", "B"],
    )

    token = chat_prime_csrf(client)
    # 从 chunk_index=1 续传：应跳过第一段 A，仅返回 B + DONE
    resp = client.post(
        "/v1/chat/completions/stream/resume",
        json={"stream_id": sid, "chunk_index": 1},
        headers={
            "X-User-Id": uid,
            "X-CSRF-Token": token,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert '"content": "A"' not in body
    assert '"content": "B"' in body
    assert "[DONE]" in body


def test_stream_resume_without_csrf_header_returns_403(chat_stream_resume_client: tuple[TestClient, StreamResumeStore]) -> None:
    client, _store = chat_stream_resume_client
    chat_prime_csrf(client)
    resp = client.post(
        "/v1/chat/completions/stream/resume",
        json={"stream_id": "any", "chunk_index": 0},
        headers={"X-User-Id": "u"},
    )
    assert resp.status_code == 403
    assert "CSRF" in resp.json().get("detail", "")


def test_stream_resume_disabled_returns_structured_404(
    chat_stream_resume_client: tuple[TestClient, StreamResumeStore],
) -> None:
    client, _store = chat_stream_resume_client
    token = chat_prime_csrf(client)
    prev_resume = bool(getattr(settings, "chat_stream_resume_enabled", True))
    settings.chat_stream_resume_enabled = False
    try:
        resp = client.post(
            "/v1/chat/completions/stream/resume",
            json={"stream_id": "disabled-stream-id-0001", "chunk_index": 0},
            headers={
                "X-User-Id": "u-disabled",
                "X-CSRF-Token": token,
            },
        )
        assert resp.status_code == 404
        payload = resp.json()
        assert payload.get("error", {}).get("code") == "stream_resume_disabled"
    finally:
        settings.chat_stream_resume_enabled = prev_resume


def test_stream_resume_chunk_index_out_of_range_returns_timeout_error_chunk(
    chat_stream_resume_client: tuple[TestClient, StreamResumeStore],
) -> None:
    client, store = chat_stream_resume_client
    uid = "resume-timeout-user"
    sid = "resume-integration-sid-0004"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=uid,
        completion_id="chatcmpl-timeout",
        created=1700000002,
        contents=["only-one"],
        append_done=False,
        finish=False,
    )

    token = chat_prime_csrf(client)
    prev_wait = int(getattr(settings, "chat_stream_resume_wait_timeout_seconds", 120) or 120)
    settings.chat_stream_resume_wait_timeout_seconds = 1
    try:
        # chunk_index=5 越界：会等待 1s，随后返回 timeout 错误 chunk + DONE
        resp = client.post(
            "/v1/chat/completions/stream/resume",
            json={"stream_id": sid, "chunk_index": 5},
            headers={
                "X-User-Id": uid,
                "X-CSRF-Token": token,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.text
        assert "stream resume wait timeout" in body
        assert "[DONE]" in body
    finally:
        settings.chat_stream_resume_wait_timeout_seconds = prev_wait


def test_stream_resume_wait_timeout_log_includes_header_correlation(
    chat_stream_resume_client: tuple[TestClient, StreamResumeStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式传入 X-Request-Id / X-Trace-Id 时，续传超时日志应与请求头一致（便于与上游对账）。"""
    captured: list[dict] = []

    def _fake_log_structured(_component: str, event: str, **kwargs) -> None:
        if event == "chat_stream_resume_wait_timeout":
            captured.append(dict(kwargs))

    monkeypatch.setattr("api.chat.log_structured", _fake_log_structured)

    client, store = chat_stream_resume_client
    uid = "resume-log-corr-user"
    sid = "resume-integration-sid-0005"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=uid,
        completion_id="chatcmpl-corr",
        created=1700000003,
        contents=["x"],
        append_done=False,
        finish=False,
    )

    token = chat_prime_csrf(client)
    prev_wait = int(getattr(settings, "chat_stream_resume_wait_timeout_seconds", 120) or 120)
    settings.chat_stream_resume_wait_timeout_seconds = 1
    try:
        client.post(
            "/v1/chat/completions/stream/resume",
            json={"stream_id": sid, "chunk_index": 9},
            headers={
                "X-User-Id": uid,
                "X-CSRF-Token": token,
                "X-Request-Id": "custom-req-99",
                "X-Trace-Id": "custom-trace-88",
            },
        )
    finally:
        settings.chat_stream_resume_wait_timeout_seconds = prev_wait

    assert len(captured) == 1
    assert captured[0].get("request_id") == "custom-req-99"
    assert captured[0].get("trace_id") == "custom-trace-88"
    assert captured[0].get("stream_id")


def test_stream_resume_wait_timeout_log_matches_request_trace_response_headers(
    chat_stream_resume_client: tuple[TestClient, StreamResumeStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未自定义追踪头时，续传超时日志中的 request_id/trace_id 应与响应头（RequestTrace 注入）一致。"""
    captured: list[dict] = []

    def _fake_log_structured(_component: str, event: str, **kwargs) -> None:
        if event == "chat_stream_resume_wait_timeout":
            captured.append(dict(kwargs))

    monkeypatch.setattr("api.chat.log_structured", _fake_log_structured)

    client, store = chat_stream_resume_client
    uid = "resume-log-state-user"
    sid = "resume-integration-sid-0006"
    chat_seed_stream_store(
        store,
        stream_id=sid,
        user_id=uid,
        completion_id="chatcmpl-state",
        created=1700000004,
        contents=["y"],
        append_done=False,
        finish=False,
    )

    token = chat_prime_csrf(client)
    prev_wait = int(getattr(settings, "chat_stream_resume_wait_timeout_seconds", 120) or 120)
    settings.chat_stream_resume_wait_timeout_seconds = 1
    try:
        resp = client.post(
            "/v1/chat/completions/stream/resume",
            json={"stream_id": sid, "chunk_index": 9},
            headers={
                "X-User-Id": uid,
                "X-CSRF-Token": token,
            },
        )
    finally:
        settings.chat_stream_resume_wait_timeout_seconds = prev_wait

    assert resp.status_code == 200, resp.text
    hdr_rid = resp.headers.get("X-Request-Id")
    hdr_tid = resp.headers.get("X-Trace-Id")
    assert hdr_rid and hdr_tid
    assert len(captured) == 1
    assert captured[0].get("request_id") == hdr_rid
    assert captured[0].get("trace_id") == hdr_tid
