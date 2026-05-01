"""FastAPI RequestValidationError：生产环境不返回 Pydantic loc/type 明细。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.errors import register_error_handlers
from config.settings import settings


def test_request_validation_returns_errors_when_debug_true(monkeypatch):
    monkeypatch.setattr(settings, "debug", True)
    app = FastAPI()
    register_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.post("/x")
    def _x(body: Body) -> dict[str, int]:
        return {"n": body.n}

    c = TestClient(app)
    r = c.post("/x", json={"n": "not-int"})
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body.get("detail"), list)
    assert len(body["detail"]) >= 1


def test_request_validation_envelope_without_field_details_when_debug_false(monkeypatch):
    monkeypatch.setattr(settings, "debug", False)
    app = FastAPI()
    register_error_handlers(app)

    class Body(BaseModel):
        n: int

    @app.post("/x")
    def _x(body: Body) -> dict[str, int]:
        return {"n": body.n}

    c = TestClient(app)
    r = c.post("/x", json={"n": "not-int"})
    assert r.status_code == 422
    body = r.json()
    assert body.get("error", {}).get("code") == "request_validation_error"
    assert body.get("error", {}).get("details") is None
    detail = body.get("detail")
    assert isinstance(detail, str)
    assert "loc" not in body and "type" not in body
