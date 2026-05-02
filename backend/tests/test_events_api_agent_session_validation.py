"""agent-session 路径：session id 校验与 LIKE 转义（生产向输入约束）。"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from api import events as events_api
from api.errors import APIException
from tests.helpers import make_fastapi_app_router_only

pytestmark = pytest.mark.no_fallback


def test_validate_agent_session_id_accepts_common_formats() -> None:
    assert events_api._validate_agent_session_id_value("asess_abcd1234ef56") == "asess_abcd1234ef56"
    assert events_api._validate_agent_session_id_value("sess-01_2.X@local") == "sess-01_2.X@local"


def test_validate_agent_session_id_rejects_any_whitespace_in_raw_string() -> None:
    """路径参数中含任意空白（含首尾 tab）一律拒绝，避免 strip 后误放行。"""
    for bad in (" bad", "bad ", "\tbad", "bad\t"):
        with pytest.raises(APIException) as ei:
            events_api._validate_agent_session_id_value(bad)
        assert ei.value.status_code == 400


def test_validate_agent_session_id_rejects_like_metachars_and_injection_shape() -> None:
    for bad in ("", "a" * 129, "pct%", "quote\"", "semi;", "x/y", "x\ny", "two words", "bad\t"):
        with pytest.raises(APIException) as ei:
            events_api._validate_agent_session_id_value(bad)
        assert ei.value.status_code == 400
        assert ei.value.code == "events_invalid_agent_session_id"


def test_validate_agent_session_id_allows_underscore() -> None:
    assert events_api._validate_agent_session_id_value("sess_with_under") == "sess_with_under"


def test_payload_like_pattern_escapes_percent_and_underscore() -> None:
    """LIKE 中 % _ 为通配符；须 ESCAPE 反斜杠（见路由 .like(..., escape='\\\\')）。"""
    p_pct = events_api._payload_json_session_substring_like_pattern("x%y")
    assert "\\%" in p_pct
    p_us = events_api._payload_json_session_substring_like_pattern("a_b")
    assert "\\_" in p_us


def test_get_agent_session_returns_400_for_invalid_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """路由层：非法 session id 在访问 DB 前应 400。"""

    async def _no_db(*_a, **_k):
        raise AssertionError("db should not be opened for invalid session id")

    monkeypatch.setattr(events_api, "_get_db", _no_db)

    app = make_fastapi_app_router_only(events_api)

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = "default"
        return await call_next(request)

    client = TestClient(app)
    # %25 → 路径参数解码后为字面量 %
    r = client.get("/api/events/agent-session/has%25pct")
    assert r.status_code == 400
    err = r.json().get("error") or {}
    assert err.get("code") == "events_invalid_agent_session_id"
