from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from tests.helpers import make_fastapi_app_router_only, session_factory_as_get_db_override
from middleware.audit_log import AuditLogMiddleware
from middleware.rbac_enforcement import RBACEnforcementMiddleware


def test_audit_middleware_uses_request_db_engine_over_get_engine(tmp_path, monkeypatch):
    """审计写库优先使用 request.state（与 Depends/get_db override 同引擎），而非裸 get_engine()。"""
    import core.data.base as data_base

    from core.data.base import Base, get_db
    from core.data.models.audit import AuditLogORM

    primary = create_engine(f"sqlite:///{tmp_path}/primary.db", connect_args={"check_same_thread": False})
    decoy = create_engine(f"sqlite:///{tmp_path}/decoy.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=primary)
    Base.metadata.create_all(bind=decoy)
    factory = sessionmaker(
        bind=primary, autocommit=False, autoflush=False, expire_on_commit=False
    )

    monkeypatch.setattr(data_base, "get_engine", lambda: decoy)

    prev_enabled = settings.audit_log_enabled
    prev_prefixes = settings.audit_log_path_prefixes
    prev_get = settings.audit_log_include_get
    try:
        settings.audit_log_enabled = True
        settings.audit_log_path_prefixes = "/api/v1/workflows"
        settings.audit_log_include_get = True

        app = make_fastapi_app_router_only()
        app.add_middleware(AuditLogMiddleware)

        app.dependency_overrides[get_db] = session_factory_as_get_db_override(factory)

        @app.get("/api/v1/workflows/ping")
        def ping(_db: Session = Depends(get_db)):
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/api/v1/workflows/ping")
        assert resp.status_code == 200
    finally:
        settings.audit_log_enabled = prev_enabled
        settings.audit_log_path_prefixes = prev_prefixes
        settings.audit_log_include_get = prev_get

    with factory() as db:
        assert db.query(AuditLogORM).count() == 1

    decoy_factory = sessionmaker(
        bind=decoy, autocommit=False, autoflush=False, expire_on_commit=False
    )
    with decoy_factory() as db:
        assert db.query(AuditLogORM).count() == 0


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

        app = make_fastapi_app_router_only()
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

        app = make_fastapi_app_router_only()
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

        app = make_fastapi_app_router_only()
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
