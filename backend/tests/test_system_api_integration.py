from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import system as system_api
from api.errors import register_error_handlers


def _build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(system_api.router)
    app.dependency_overrides[system_api.require_authenticated_platform_admin] = lambda: None
    app.dependency_overrides[system_api.require_platform_admin] = lambda: None
    return TestClient(app)


@pytest.mark.no_fallback
def test_update_feature_flags_invalid_payload_returns_structured_error(fallback_probe):
    client = _build_client()

    resp = client.post("/api/system/feature-flags", json={"flags": "not-an-object"})
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("detail") == "flags must be object"
    assert body.get("error", {}).get("code") == "system_feature_flags_invalid"
    assert fallback_probe == []


def test_kernel_status_endpoint_returns_expected_shape():
    client = _build_client()

    resp = client.get("/api/system/kernel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("enabled"), bool)
    assert body.get("can_toggle") is True
    assert "description" in body


def test_feature_flags_update_and_fetch_roundtrip(monkeypatch):
    client = _build_client()
    saved: dict = {}

    def _fake_set_feature_flags(flags, tenant_id=None):
        saved["tenant_id"] = tenant_id
        saved["flags"] = dict(flags)
        return saved["flags"]

    def _fake_get_feature_flags(tenant_id=None):
        return saved.get("flags", {})

    monkeypatch.setattr(system_api, "set_feature_flags", _fake_set_feature_flags)
    monkeypatch.setattr(system_api, "get_feature_flags", _fake_get_feature_flags)

    update_resp = client.post("/api/system/feature-flags", json={"flags": {"beta_ui": True}})
    assert update_resp.status_code == 200
    assert update_resp.json().get("flags", {}).get("beta_ui") is True

    get_resp = client.get("/api/system/feature-flags")
    assert get_resp.status_code == 200
    assert get_resp.json().get("flags", {}).get("beta_ui") is True
