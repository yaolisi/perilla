"""TrustedHostMiddleware：非空 TRUSTED_HOSTS 时拒绝非法 Host（与 main 挂载方式一致）。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware


def test_trusted_host_middleware_allows_listed_host():
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["api.example.com"])

    @app.get("/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "1"}

    c = TestClient(app)
    r = c.get("/ping", headers={"Host": "api.example.com"})
    assert r.status_code == 200


def test_trusted_host_middleware_blocks_default_testclient_host():
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["api.example.com"])

    @app.get("/ping")
    def _ping() -> dict[str, str]:
        return {"ok": "1"}

    c = TestClient(app)
    r = c.get("/ping")
    assert r.status_code == 400
