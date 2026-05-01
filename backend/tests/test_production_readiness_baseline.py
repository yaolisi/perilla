import types

from fastapi.testclient import TestClient

from config.settings import settings
from core.system.queue_summary import build_unified_queue_summary
from core.system.storage_strategy import detect_storage_backend, storage_readiness
from middleware.api_key_scope import _parse_scopes, ApiKeyScopeMiddleware
from middleware.tenant_context import TenantContextMiddleware
from scripts.slo_check import evaluate
from tests.helpers import make_fastapi_app_router_only


def test_parse_scopes_json():
    out = _parse_scopes('{"k1":["admin","audit:read"],"k2":["read"]}')
    assert out["k1"] == ["admin", "audit:read"]
    assert out["k2"] == ["read"]


def test_api_key_scope_enforcement_blocks_missing_scope():
    prev = settings.api_key_scopes_json
    try:
        settings.api_key_scopes_json = '{"k-read":["read"]}'
        app = make_fastapi_app_router_only()
        app.add_middleware(ApiKeyScopeMiddleware)

        @app.get("/api/v1/audit/logs")
        def logs():
            return {"ok": True}

        c = TestClient(app)
        resp = c.get("/api/v1/audit/logs", headers={"X-Api-Key": "k-read"})
        assert resp.status_code == 403
    finally:
        settings.api_key_scopes_json = prev


def test_api_key_scope_enforcement_allows_admin():
    prev = settings.api_key_scopes_json
    try:
        settings.api_key_scopes_json = '{"k-admin":["admin"]}'
        app = make_fastapi_app_router_only()
        app.add_middleware(ApiKeyScopeMiddleware)

        @app.post("/api/v1/workflows/x")
        def write():
            return {"ok": True}

        c = TestClient(app)
        resp = c.post("/api/v1/workflows/x", headers={"X-Api-Key": "k-admin"})
        assert resp.status_code == 200
    finally:
        settings.api_key_scopes_json = prev


def test_tenant_enforcement_protected_path():
    prev_enf = settings.tenant_enforcement_enabled
    prev_default = settings.tenant_default_id
    try:
        settings.tenant_enforcement_enabled = True
        settings.tenant_default_id = "default"
        app = make_fastapi_app_router_only()
        app.add_middleware(TenantContextMiddleware)

        @app.get("/api/v1/workflows/w1")
        def w():
            return {"ok": True}

        c = TestClient(app)
        resp = c.get("/api/v1/workflows/w1")
        assert resp.status_code == 400
    finally:
        settings.tenant_enforcement_enabled = prev_enf
        settings.tenant_default_id = prev_default


def test_storage_strategy_detection():
    assert detect_storage_backend("postgresql://x") == "postgresql"
    assert detect_storage_backend("mysql://x") == "mysql"
    assert detect_storage_backend("") == "sqlite"
    r = storage_readiness("")
    assert r["backend"] == "sqlite"


def test_unified_queue_summary_shape():
    out = build_unified_queue_summary(2, 3, 1, 4)
    assert out["workflow"]["running"] == 2
    assert out["image_generation"]["pending"] == 3
    assert out["total_load"] == 6


def test_feature_flags_store_roundtrip(monkeypatch):
    import core.system.feature_flags as ff

    class FakeStore:
        def __init__(self):
            self.v = {}

        def get_setting(self, key, default=None):
            return self.v.get(key, default)

        def set_setting(self, key, value):
            self.v[key] = value

    store = FakeStore()
    monkeypatch.setattr(ff, "get_system_settings_store", lambda: store)
    saved = ff.set_feature_flags({"a": True, "b": 0}, tenant_id="t1")
    assert saved == {"a": True, "b": False}
    got = ff.get_feature_flags(tenant_id="t1")
    assert got["a"] is True
    got_other = ff.get_feature_flags(tenant_id="t2")
    assert got_other == {}


def test_slo_evaluate():
    summary = {"failed_rate": 0.01, "sqlite": {"avg_p95_ms": 300}}
    out = evaluate(summary, fail_rate_slo=0.02, p95_slo_ms=500)
    assert out["overall_ok"] is True


def test_audit_query_tenant_filter(monkeypatch):
    import core.security.audit_service as audit

    class FakeRow:
        def __init__(self):
            self.id = "1"
            self.created_at = None
            self.user_id = "u"
            self.tenant_id = "t1"
            self.platform_role = "admin"
            self.method = "GET"
            self.path = "/x"
            self.status_code = 200
            self.request_id = None
            self.trace_id = None
            self.client_ip = None
            self.detail_json = None

    class FakeScalar:
        def __init__(self, val):
            self._v = val

        def scalar(self):
            return self._v

        def all(self):
            return [FakeRow()]

    class FakeExec:
        def __init__(self):
            self.calls = 0

        def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeScalar(1)
            return types.SimpleNamespace(scalars=lambda: FakeScalar(None))

    db = FakeExec()
    items, total = audit.query_audit_logs(db, tenant_id="t1", limit=10, offset=0)
    assert total == 1
    assert items[0]["tenant_id"] == "t1"


def test_workflow_service_forwards_tenant_for_get():
    from core.workflows.services.workflow_service import WorkflowService

    class DummyRepo:
        def __init__(self):
            self.args = None

        def get_by_id(self, workflow_id, tenant_id=None):
            self.args = (workflow_id, tenant_id)
            return None

    service = WorkflowService(db=None)
    repo = DummyRepo()
    service.repository = repo
    service.get_workflow("wf-1", tenant_id="t-1")
    assert repo.args == ("wf-1", "t-1")


def test_workflow_service_forwards_tenant_for_list_and_count():
    from core.workflows.services.workflow_service import WorkflowService

    class DummyRepo:
        def __init__(self):
            self.list_kwargs = None
            self.count_kwargs = None

        def list_workflows(self, **kwargs):
            self.list_kwargs = kwargs
            return []

        def count_workflows(self, **kwargs):
            self.count_kwargs = kwargs
            return 0

    service = WorkflowService(db=None)
    repo = DummyRepo()
    service.repository = repo
    service.list_workflows(namespace="ns", tenant_id="t-1", owner_id="u1")
    service.count_workflows(namespace="ns", tenant_id="t-1", owner_id="u1")
    assert repo.list_kwargs["tenant_id"] == "t-1"
    assert repo.count_kwargs["tenant_id"] == "t-1"


def test_apply_production_security_defaults_in_non_debug():
    import types as _types
    from config.settings import apply_production_security_defaults

    s = _types.SimpleNamespace(
        debug=False,
        rbac_enabled=False,
        rbac_enforcement=False,
        tenant_enforcement_enabled=False,
        tenant_api_key_binding_enabled=False,
        file_read_allowed_roots="/",
        production_file_read_required_roots="./data",
    )
    changes = apply_production_security_defaults(s)
    assert set(changes) >= {
        "rbac_enabled",
        "rbac_enforcement",
        "tenant_enforcement_enabled",
        "tenant_api_key_binding_enabled",
        "file_read_allowed_roots",
    }
    assert s.rbac_enabled is True
    assert s.rbac_enforcement is True
    assert s.tenant_enforcement_enabled is True
    assert s.tenant_api_key_binding_enabled is True
    assert s.file_read_allowed_roots == "./data"


def test_apply_production_security_defaults_skip_in_debug():
    import types as _types
    from config.settings import apply_production_security_defaults

    s = _types.SimpleNamespace(
        debug=True,
        rbac_enabled=False,
        rbac_enforcement=False,
        tenant_enforcement_enabled=False,
        tenant_api_key_binding_enabled=False,
        file_read_allowed_roots="/",
        production_file_read_required_roots="./data",
    )
    changes = apply_production_security_defaults(s)
    assert changes == []
    assert s.rbac_enabled is False
    assert s.file_read_allowed_roots == "/"


def test_validate_production_security_guardrails_blocks_high_risk():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        file_read_allowed_roots="/",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="",
    )
    issues = validate_production_security_guardrails(s)
    assert any("file_read_allowed_roots" in x for x in issues)
    assert any("cors_allowed_origins" in x for x in issues)
    assert any("tool_net_http_allowed_hosts" in x for x in issues)


def test_validate_production_security_guardrails_allows_safe_profile():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
    )
    issues = validate_production_security_guardrails(s)
    assert issues == []


def test_security_guardrails_strict_default_true():
    from config.settings import Settings

    s = Settings()
    assert s.security_guardrails_strict is True
