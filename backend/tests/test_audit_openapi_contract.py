from __future__ import annotations

from fastapi.testclient import TestClient

from api import audit as audit_api
from core.security.deps import require_audit_reader
from core.security.rbac import PlatformRole

from tests.helpers import make_fastapi_app_router_only


def _client() -> TestClient:
    app = make_fastapi_app_router_only(audit_api)
    app.dependency_overrides[require_audit_reader] = lambda: PlatformRole.ADMIN
    return TestClient(app)


def _detail_refs(detail_schema: dict) -> set[str]:
    refs: set[str] = set()
    if "$ref" in detail_schema:
        refs.add(detail_schema["$ref"])
    for opt in detail_schema.get("anyOf") or []:
        if isinstance(opt, dict) and "$ref" in opt:
            refs.add(opt["$ref"])
    return refs


def test_openapi_audit_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    lst = paths["/api/v1/audit/logs"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert lst == "#/components/schemas/AuditLogListResponse"
    assert schemas["AuditLogListResponse"]["properties"]["items"]["items"]["$ref"] == "#/components/schemas/AuditLogItem"
    detail_prop = schemas["AuditLogItem"]["properties"]["detail"]
    assert "#/components/schemas/AuditLogDetail" in _detail_refs(detail_prop)
