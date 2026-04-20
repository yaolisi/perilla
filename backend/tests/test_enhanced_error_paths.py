from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from core.security.rbac import PlatformRole
from middleware.rbac_context import RBACContextMiddleware
from middleware.rbac_enforcement import RBACEnforcementMiddleware
from middleware.request_trace import RequestTraceMiddleware


def test_viewer_write_blocked_when_enforced():
    prev_enabled = settings.rbac_enabled
    prev_enforcement = settings.rbac_enforcement
    prev_viewer = settings.rbac_viewer_api_keys
    try:
        settings.rbac_enabled = True
        settings.rbac_enforcement = True
        settings.rbac_viewer_api_keys = "viewer-key"

        app = FastAPI()
        app.add_middleware(RequestTraceMiddleware, header_name="X-Request-Id")
        app.add_middleware(RBACContextMiddleware, api_key_header="X-Api-Key")
        app.add_middleware(RBACEnforcementMiddleware)

        @app.post("/api/v1/workflows/demo")
        def write_workflow():
            return {"ok": True}

        client = TestClient(app)
        resp = client.post("/api/v1/workflows/demo", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 403
        assert "viewer role" in resp.json()["detail"]
    finally:
        settings.rbac_enabled = prev_enabled
        settings.rbac_enforcement = prev_enforcement
        settings.rbac_viewer_api_keys = prev_viewer


def test_operator_write_allowed_when_enforced():
    prev_enabled = settings.rbac_enabled
    prev_enforcement = settings.rbac_enforcement
    prev_operator = settings.rbac_operator_api_keys
    try:
        settings.rbac_enabled = True
        settings.rbac_enforcement = True
        settings.rbac_operator_api_keys = "op-key"

        app = FastAPI()
        app.add_middleware(RBACContextMiddleware, api_key_header="X-Api-Key")
        app.add_middleware(RBACEnforcementMiddleware)

        @app.post("/api/v1/workflows/demo")
        def write_workflow():
            return {"ok": True}

        client = TestClient(app)
        resp = client.post("/api/v1/workflows/demo", headers={"X-Api-Key": "op-key"})
        assert resp.status_code == 200
    finally:
        settings.rbac_enabled = prev_enabled
        settings.rbac_enforcement = prev_enforcement
        settings.rbac_operator_api_keys = prev_operator


def test_traceparent_invalid_fallback_to_request_id():
    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware, header_name="X-Request-Id")

    @app.get("/ok")
    def ok():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/ok", headers={"traceparent": "bad-traceparent", "X-Request-Id": "req-1"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-Id"] == "req-1"
    assert resp.headers["X-Trace-Id"] == "req-1"


def test_trace_header_pollution_is_rejected_and_fallback():
    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware, header_name="X-Request-Id")

    @app.get("/ok")
    def ok():
        return {"ok": True}

    client = TestClient(app)
    polluted = "bad\r\nInjected: x"
    resp = client.get("/ok", headers={"X-Trace-Id": polluted, "X-Request-Id": "req-safe"})
    assert resp.status_code == 200
    assert resp.headers["X-Trace-Id"] == "req-safe"


def test_audit_access_denied_for_non_admin():
    from core.security.deps import require_audit_reader
    from fastapi import HTTPException
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/api/v1/audit/logs", "headers": []}
    request = Request(scope)
    request.state.platform_role = PlatformRole.OPERATOR

    try:
        require_audit_reader(request)
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


def test_platform_admin_required_for_system_writes():
    from core.security.deps import require_platform_admin
    from fastapi import HTTPException
    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/api/system/config", "headers": []}
    request = Request(scope)
    request.state.platform_role = PlatformRole.OPERATOR

    try:
        require_platform_admin(request)
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 403
