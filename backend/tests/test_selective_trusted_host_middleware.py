"""SelectiveTrustedHostMiddleware：探针/指标路径不因 Pod IP Host 被拒。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.trusted_host import SelectiveTrustedHostMiddleware


def test_health_path_allowed_even_when_host_not_in_list():
    app = FastAPI()
    app.add_middleware(
        SelectiveTrustedHostMiddleware,
        allowed_hosts=["api.example.com"],
        www_redirect=False,
    )

    @app.get("/api/health")
    def _h() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/x")
    def _x() -> dict[str, str]:
        return {"k": "v"}

    c = TestClient(app)
    bad_host = {"Host": "10.244.0.17"}
    assert c.get("/api/health", headers=bad_host).status_code == 200
    assert c.get("/api/v1/x", headers=bad_host).status_code == 400


def test_health_path_requires_matching_host_when_exempt_disabled(monkeypatch):
    monkeypatch.setattr(settings, "trusted_host_exempt_ops_paths", False)
    app = FastAPI()
    app.add_middleware(
        SelectiveTrustedHostMiddleware,
        allowed_hosts=["api.example.com"],
        www_redirect=False,
    )

    @app.get("/api/health")
    def _h() -> dict[str, bool]:
        return {"ok": True}

    c = TestClient(app)
    bad_host = {"Host": "10.244.0.17"}
    assert c.get("/api/health", headers=bad_host).status_code == 400


def test_metrics_path_allowed_when_configured():
    app = FastAPI()
    app.add_middleware(
        SelectiveTrustedHostMiddleware,
        allowed_hosts=["api.example.com"],
        www_redirect=False,
    )

    @app.get("/metrics")
    def _m() -> str:
        return "# noop"

    c = TestClient(app)
    assert c.get("/metrics", headers={"Host": "127.0.0.1"}).status_code == 200
