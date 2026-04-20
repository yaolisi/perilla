from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.audit_log import AuditLogMiddleware
from middleware.rbac_enforcement import RBACEnforcementMiddleware


def test_audit_middleware_degrades_when_db_session_broken(monkeypatch):
    prev_enabled = settings.audit_log_enabled
    prev_prefixes = settings.audit_log_path_prefixes
    prev_get = settings.audit_log_include_get
    try:
        settings.audit_log_enabled = True
        settings.audit_log_path_prefixes = "/api/v1/workflows"
        settings.audit_log_include_get = True

        import core.data.base as data_base

        class _BrokenSession:
            def __call__(self):
                raise RuntimeError("db down")

        monkeypatch.setattr(data_base, "SessionLocal", _BrokenSession())

        app = FastAPI()
        app.add_middleware(AuditLogMiddleware)

        @app.get("/api/v1/workflows/ping")
        def ping():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/api/v1/workflows/ping")
        # 审计失败应被吞掉，不影响业务响应
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    finally:
        settings.audit_log_enabled = prev_enabled
        settings.audit_log_path_prefixes = prev_prefixes
        settings.audit_log_include_get = prev_get


def test_audit_middleware_degrades_when_append_fails(monkeypatch):
    prev_enabled = settings.audit_log_enabled
    prev_prefixes = settings.audit_log_path_prefixes
    try:
        settings.audit_log_enabled = True
        settings.audit_log_path_prefixes = "/api/v1/workflows"

        import core.security.audit_service as audit_service

        def _raise_append(*args, **kwargs):
            raise RuntimeError("append fail")

        monkeypatch.setattr(audit_service, "append_audit_log", _raise_append)

        app = FastAPI()
        app.add_middleware(AuditLogMiddleware)

        @app.post("/api/v1/workflows/ping")
        def ping():
            return {"ok": True}

        client = TestClient(app)
        resp = client.post("/api/v1/workflows/ping")
        assert resp.status_code == 200
    finally:
        settings.audit_log_enabled = prev_enabled
        settings.audit_log_path_prefixes = prev_prefixes


def test_rbac_enforcement_fallback_blocks_viewer_without_context_middleware():
    prev_enabled = settings.rbac_enabled
    prev_enforcement = settings.rbac_enforcement
    prev_viewer = settings.rbac_viewer_api_keys
    prev_header = settings.api_rate_limit_api_key_header
    try:
        settings.rbac_enabled = True
        settings.rbac_enforcement = True
        settings.rbac_viewer_api_keys = "viewer-key"
        settings.api_rate_limit_api_key_header = "X-Api-Key"

        app = FastAPI()
        # 故意不挂 RBACContextMiddleware，验证 Enforcement 兜底逻辑
        app.add_middleware(RBACEnforcementMiddleware)

        @app.post("/api/models/scan")
        def scan():
            return {"ok": True}

        client = TestClient(app)
        resp = client.post("/api/models/scan", headers={"X-Api-Key": "viewer-key"})
        assert resp.status_code == 403
    finally:
        settings.rbac_enabled = prev_enabled
        settings.rbac_enforcement = prev_enforcement
        settings.rbac_viewer_api_keys = prev_viewer
        settings.api_rate_limit_api_key_header = prev_header
