from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from config.settings import settings
from middleware.request_whitelist import enforce_request_body_whitelist
from middleware.sensitive_data_redaction import SensitiveDataRedactionMiddleware
from tests.helpers import make_fastapi_app_with_handlers


class LoginBody(BaseModel):
    username: str
    api_key: str
    password: str


def _create_app() -> FastAPI:
    app = make_fastapi_app_with_handlers(dependencies=[Depends(enforce_request_body_whitelist)])
    app.add_middleware(SensitiveDataRedactionMiddleware)

    @app.post("/login")
    def login(body: LoginBody):
        return {
            "username": body.username,
            "api_key": body.api_key,
            "password": body.password,
        }

    return app


def test_request_whitelist_rejects_unknown_fields():
    prev = settings.api_request_whitelist_enabled
    try:
        settings.api_request_whitelist_enabled = True
        client = TestClient(_create_app())
        resp = client.post(
            "/login",
            json={
                "username": "u1",
                "api_key": "abcdefgh12345678",
                "password": "p@ssw0rd",
                "unexpected": "boom",
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "request_unknown_fields"
        details = body["error"].get("details") or {}
        assert "unexpected" in details.get("unknown_fields", [])
    finally:
        settings.api_request_whitelist_enabled = prev


def test_response_sensitive_fields_are_redacted():
    prev_enabled = settings.data_redaction_enabled
    prev_fields = settings.data_redaction_sensitive_fields
    try:
        settings.data_redaction_enabled = True
        settings.data_redaction_sensitive_fields = "api_key,password"
        client = TestClient(_create_app())
        resp = client.post(
            "/login",
            json={
                "username": "u1",
                "api_key": "abcdefgh12345678",
                "password": "passw0rd1234",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "u1"
        assert body["api_key"].startswith("abcd")
        assert body["api_key"].endswith("5678")
        assert "*" in body["api_key"]
        assert body["password"].startswith("pass")
        assert body["password"].endswith("1234")
    finally:
        settings.data_redaction_enabled = prev_enabled
        settings.data_redaction_sensitive_fields = prev_fields
