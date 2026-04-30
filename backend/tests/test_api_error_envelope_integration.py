from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.errors import (
    raise_api_error,
    register_error_handlers,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/api/core/raw-http-error")
    async def _raw_http_error():
        raise_api_error(
            status_code=400,
            code="http_400",
            message="bad request",
        )

    @app.get("/api/core/typed-http-error")
    async def _typed_http_error():
        raise_api_error(
            status_code=422,
            code="invalid_payload",
            message="payload validation failed",
            details={"field": "messages"},
        )

    @app.get("/api/core/mcp-not-found")
    async def _mcp_not_found():
        raise_api_error(
            status_code=404,
            code="mcp_server_not_found",
            message="MCP server not found",
        )

    @app.get(
        "/api/core/framework-http-error",
        responses={401: {"description": "Unauthorized by framework"}},
    )
    async def _framework_http_error():
        raise HTTPException(status_code=401, detail="unauthorized by framework")

    @app.get("/api/core/workflow-not-found")
    async def _workflow_not_found():
        raise_api_error(
            status_code=404,
            code="workflow_not_found",
            message="workflow not found",
        )

    @app.get("/api/core/tool-not-found")
    async def _tool_not_found():
        raise_api_error(
            status_code=404,
            code="tool_not_found",
            message="tool not found",
        )

    return app


def test_raw_http_exception_is_wrapped_to_standard_error_payload():
    client = TestClient(_build_app())
    resp = client.get("/api/core/raw-http-error")
    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"] == "bad request"
    assert body["error"]["code"] == "http_400"
    assert body["error"]["message"] == "bad request"


def test_raise_api_error_keeps_custom_error_code_and_details():
    client = TestClient(_build_app())
    resp = client.get("/api/core/typed-http-error")
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "payload validation failed"
    assert body["error"]["code"] == "invalid_payload"
    assert body["error"]["details"]["field"] == "messages"


def test_raise_api_error_localizes_message_by_accept_language():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/typed-http-error",
        headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "请求参数校验失败"
    assert body["error"]["message"] == "请求参数校验失败"
    assert body["error"]["code"] == "invalid_payload"


def test_framework_http_exception_uses_fallback_code():
    client = TestClient(_build_app())
    resp = client.get("/api/core/framework-http-error")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"] == "unauthorized by framework"
    assert body["error"]["code"] == "http_unexpected_401"
    assert body["error"]["details"]["source"] == "http_exception_fallback"


def test_mcp_not_found_message_is_localized():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/mcp-not-found",
        headers={"Accept-Language": "zh-CN"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "MCP 服务不存在"
    assert body["error"]["message"] == "MCP 服务不存在"
    assert body["error"]["code"] == "mcp_server_not_found"


def test_workflow_not_found_is_english_when_accept_language_is_english():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/workflow-not-found",
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "workflow not found"
    assert body["error"]["message"] == "workflow not found"
    assert body["error"]["code"] == "workflow_not_found"


def test_tool_not_found_is_localized_to_zh():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/tool-not-found",
        headers={"Accept-Language": "zh-CN"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "工具不存在"
    assert body["error"]["message"] == "工具不存在"
    assert body["error"]["code"] == "tool_not_found"


def test_accept_language_with_spaces_respects_q_priority():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/tool-not-found",
        headers={"Accept-Language": "en-US,en;q=0.9, zh-CN;q=0.8"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "tool not found"
    assert body["error"]["message"] == "tool not found"
    assert body["error"]["code"] == "tool_not_found"


def test_accept_language_zh_with_higher_q_wins_even_if_not_first():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/tool-not-found",
        headers={"Accept-Language": "en-US;q=0.5, zh-CN;q=0.9"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "工具不存在"
    assert body["error"]["message"] == "工具不存在"
    assert body["error"]["code"] == "tool_not_found"


def test_accept_language_wildcard_falls_back_to_default_english():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/tool-not-found",
        headers={"Accept-Language": "*"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "tool not found"
    assert body["error"]["message"] == "tool not found"
    assert body["error"]["code"] == "tool_not_found"


def test_accept_language_invalid_q_falls_back_gracefully():
    client = TestClient(_build_app())
    resp = client.get(
        "/api/core/tool-not-found",
        headers={"Accept-Language": "zh-CN;q=abc, en-US;q=0.7"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "tool not found"
    assert body["error"]["message"] == "tool not found"
    assert body["error"]["code"] == "tool_not_found"


def test_framework_http_exception_triggers_fallback_observer(fallback_probe):
    client = TestClient(_build_app())
    resp = client.get("/api/core/framework-http-error")
    assert resp.status_code == 401
    assert fallback_probe == [
        (401, "unauthorized by framework", "/api/core/framework-http-error")
    ]


