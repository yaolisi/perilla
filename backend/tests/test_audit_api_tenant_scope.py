"""GET /api/v1/audit/logs 须始终按 resolve_api_tenant_id 过滤，避免 tenant_id=None 时跨租户全表可见。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.audit import router as audit_router
from config.settings import settings
from core.data.base import get_db
from core.security.deps import require_audit_reader
from core.security.rbac import PlatformRole

pytestmark = pytest.mark.tenant_isolation


def _audit_client_with_middleware(state_tenant: str | None) -> TestClient:
    app = FastAPI()

    if state_tenant is not None:

        @app.middleware("http")
        async def inject(request, call_next):  # type: ignore[no-untyped-def]
            request.state.tenant_id = state_tenant
            return await call_next(request)

    app.include_router(audit_router)

    def override_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_audit_reader] = lambda: PlatformRole.ADMIN

    return TestClient(app)


def test_audit_logs_query_scopes_to_default_when_no_state_tenant() -> None:
    captured: dict[str, object] = {}

    def fake_query(db, *, tenant_id=None, **kwargs):  # type: ignore[no-untyped-def]
        captured["tenant_id"] = tenant_id
        return [], 0

    client = _audit_client_with_middleware(None)
    from api import audit as audit_mod

    default_tid = str(getattr(settings, "tenant_default_id", "default") or "default").strip() or "default"

    with patch.object(audit_mod, "query_audit_logs", side_effect=fake_query):
        r = client.get("/api/v1/audit/logs")
    assert r.status_code == 200
    assert captured.get("tenant_id") == default_tid


def test_audit_logs_query_scopes_to_request_state_tenant() -> None:
    captured: dict[str, object] = {}

    def fake_query(db, *, tenant_id=None, **kwargs):  # type: ignore[no-untyped-def]
        captured["tenant_id"] = tenant_id
        return [], 0

    client = _audit_client_with_middleware("tenant_audit_scope_z")
    from api import audit as audit_mod

    with patch.object(audit_mod, "query_audit_logs", side_effect=fake_query):
        r = client.get("/api/v1/audit/logs")
    assert r.status_code == 200
    assert captured.get("tenant_id") == "tenant_audit_scope_z"
