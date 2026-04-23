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

    @app.get("/api/core/framework-http-error")
    async def _framework_http_error():
        raise HTTPException(status_code=401, detail="unauthorized by framework")

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


def test_framework_http_exception_uses_fallback_code():
    client = TestClient(_build_app())
    resp = client.get("/api/core/framework-http-error")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"] == "unauthorized by framework"
    assert body["error"]["code"] == "http_unexpected_401"
    assert body["error"]["details"]["source"] == "http_exception_fallback"


def test_framework_http_exception_triggers_fallback_observer(fallback_probe):
    client = TestClient(_build_app())
    resp = client.get("/api/core/framework-http-error")
    assert resp.status_code == 401
    assert fallback_probe == [
        (401, "unauthorized by framework", "/api/core/framework-http-error")
    ]


