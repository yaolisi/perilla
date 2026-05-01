"""未捕获异常：生产环境不向客户端返回异常类型详情。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.errors import register_error_handlers
from config.settings import settings
from tests.helpers.router_integration_app import make_fastapi_app_with_handlers


def test_unhandled_exception_includes_exception_class_only_when_debug(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    app = make_fastapi_app_with_handlers()

    @app.get("/boom")
    def boom():
        raise RuntimeError("internal")

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/boom")
    assert r.status_code == 500
    err = r.json().get("error") or {}
    assert err.get("details") is None


def test_unhandled_exception_includes_exception_class_when_debug_true(monkeypatch):
    monkeypatch.setattr(settings, "debug", True)
    app = make_fastapi_app_with_handlers()

    @app.get("/boom")
    def boom():
        raise ValueError("x")

    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/boom")
    assert r.status_code == 500
    err = r.json().get("error") or {}
    assert err.get("details", {}).get("exception") == "ValueError"
