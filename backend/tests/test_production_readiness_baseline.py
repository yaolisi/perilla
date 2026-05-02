import types

import pytest
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
    assert out["tenant_scope"] is False
    assert out["tenant_id"] is None


def test_unified_queue_summary_tenant_scoped_metadata():
    out = build_unified_queue_summary(1, 1, 0, 2, tenant_scope=True, tenant_id="acme")
    assert out["tenant_scope"] is True
    assert out["tenant_id"] == "acme"
    assert out["total_load"] == 2


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
        security_headers_enabled=False,
        file_read_allowed_roots="/",
        production_file_read_required_roots="./data",
        inference_cache_enabled=True,
        health_ready_strict_inference_redis=False,
        api_rate_limit_enabled=True,
        api_rate_limit_requests=120,
        api_rate_limit_redis_url="redis://localhost:6379/14",
        health_ready_strict_api_rate_limit_redis=False,
        api_rate_limit_redis_fail_closed=False,
    )
    changes = apply_production_security_defaults(s)
    assert set(changes) >= {
        "rbac_enabled",
        "rbac_enforcement",
        "tenant_enforcement_enabled",
        "tenant_api_key_binding_enabled",
        "events_strict_workflow_binding",
        "events_api_require_authenticated",
        "security_headers_enabled",
        "file_read_allowed_roots",
        "http_max_request_body_bytes",
        "chat_stream_resume_cancel_upstream_on_disconnect",
        "health_ready_strict_inference_redis",
        "health_ready_strict_api_rate_limit_redis",
        "api_rate_limit_redis_fail_closed",
    }
    assert s.rbac_enabled is True
    assert s.rbac_enforcement is True
    assert s.tenant_enforcement_enabled is True
    assert s.tenant_api_key_binding_enabled is True
    assert s.events_strict_workflow_binding is True
    assert s.events_api_require_authenticated is True
    assert s.security_headers_enabled is True
    assert s.file_read_allowed_roots == "./data"
    assert s.http_max_request_body_bytes == 52428800
    assert s.chat_stream_resume_cancel_upstream_on_disconnect is True
    assert s.health_ready_strict_inference_redis is True
    assert s.health_ready_strict_api_rate_limit_redis is True
    assert s.api_rate_limit_redis_fail_closed is True


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
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
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


def test_log_production_warns_when_events_auth_without_dedicated_events_rate_limit(monkeypatch):
    """生产启动建议：events 认证开启且未配 API_RATE_LIMIT_EVENTS_REQUESTS 时提示独立窗口。"""
    warnings: list[str] = []

    def _capture(msg: str, *a, **k) -> None:
        warnings.append(msg)

    import main as main_mod

    monkeypatch.setattr(main_mod.logger, "warning", _capture)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_enabled", True)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_requests", 120)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_events_requests", 0)
    monkeypatch.setattr(main_mod.settings, "events_api_require_authenticated", True)
    main_mod._log_production_operational_warnings()
    assert any("API_RATE_LIMIT_EVENTS_REQUESTS" in m for m in warnings)


def test_log_production_warns_when_events_audit_prefix_missing(monkeypatch):
    """审计开启且 events 要求认证时：前缀未覆盖 /api/events 则告警。"""
    warnings: list[str] = []

    def _capture(msg: str, *a, **k) -> None:
        warnings.append(msg)

    import main as main_mod

    monkeypatch.setattr(main_mod.logger, "warning", _capture)
    monkeypatch.setattr(main_mod.settings, "audit_log_enabled", True)
    monkeypatch.setattr(main_mod.settings, "events_api_require_authenticated", True)
    monkeypatch.setattr(main_mod.settings, "audit_log_path_prefixes", "/api/v1/workflows")
    main_mod._log_production_operational_warnings()
    assert any("AUDIT_LOG_PATH_PREFIXES does not cover /api/events" in m for m in warnings)


def test_log_production_warns_when_events_audit_prefix_ok_but_get_skipped(monkeypatch):
    """前缀覆盖 /api/events 且 audit_log_include_get=false 时告警 GET 未审计。"""
    warnings: list[str] = []

    def _capture(msg: str, *a, **k) -> None:
        warnings.append(msg)

    import main as main_mod

    monkeypatch.setattr(main_mod.logger, "warning", _capture)
    monkeypatch.setattr(main_mod.settings, "audit_log_enabled", True)
    monkeypatch.setattr(main_mod.settings, "events_api_require_authenticated", True)
    monkeypatch.setattr(main_mod.settings, "audit_log_path_prefixes", "/api/events")
    monkeypatch.setattr(main_mod.settings, "audit_log_include_get", False)
    main_mod._log_production_operational_warnings()
    assert any("audit_log_include_get=False" in m for m in warnings)


def test_log_production_warns_when_events_auth_but_gateway_rl_middleware_inactive(monkeypatch):
    """events 要求认证时若全局限流未挂载（与 main.py 门闩一致），提示无内置网关限流。"""
    warnings: list[str] = []

    def _capture(msg: str, *a, **k) -> None:
        warnings.append(msg)

    import main as main_mod

    monkeypatch.setattr(main_mod.logger, "warning", _capture)
    monkeypatch.setattr(main_mod.settings, "events_api_require_authenticated", True)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_enabled", True)
    monkeypatch.setattr(main_mod.settings, "api_rate_limit_requests", 0)
    main_mod._log_production_operational_warnings()
    assert any("gateway rate-limit middleware is not active" in m for m in warnings)


def test_validate_production_security_guardrails_allows_safe_profile():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
    )
    issues = validate_production_security_guardrails(s)
    assert issues == []


def test_validate_production_security_guardrails_blocks_rbac_enabled_without_api_keys():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        rbac_enabled=True,
        rbac_admin_api_keys="",
        rbac_operator_api_keys="",
        rbac_viewer_api_keys="",
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
        rbac_default_role="viewer",
    )
    issues = validate_production_security_guardrails(s)
    assert any("rbac_enabled=True" in x and "RBAC_" in x for x in issues)


def test_validate_production_security_guardrails_allows_rbac_with_any_api_key():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        rbac_enabled=True,
        rbac_default_role="viewer",
        rbac_admin_api_keys="prod-integration-admin-k",
        rbac_operator_api_keys="",
        rbac_viewer_api_keys="",
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
    )
    issues = validate_production_security_guardrails(s)
    assert issues == []


def test_validate_production_security_guardrails_blocks_rbac_default_role_operator():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        rbac_enabled=True,
        rbac_default_role="operator",
        rbac_admin_api_keys="prod-integration-admin-k",
        rbac_operator_api_keys="",
        rbac_viewer_api_keys="",
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
    )
    issues = validate_production_security_guardrails(s)
    assert any("rbac_default_role" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_placeholder_rbac_api_key():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        rbac_enabled=True,
        rbac_default_role="viewer",
        rbac_admin_api_keys="admin-key",
        rbac_operator_api_keys="",
        rbac_viewer_api_keys="",
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=True,
        tool_net_http_allowed_hosts="api.example.com,*.svc.local",
    )
    issues = validate_production_security_guardrails(s)
    assert any("RBAC_ADMIN_API_KEYS" in x for x in issues)
    assert any("placeholder" in x.lower() or "characters" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_cors_wildcard():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="*",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("'*'" in x or "*" in x for x in issues)
    assert any("cors_allowed_origins" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_cors_plain_http_origin():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="http://app.example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("https://" in x.lower() for x in issues)
    assert any("cors_allowed_origins" in x.lower() for x in issues)


def test_validate_production_security_guardrails_allows_cors_localhost_http():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="http://localhost:5173,https://console.example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert issues == []


def test_validate_production_security_guardrails_blocks_openapi_public_enabled():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        openapi_public_enabled=True,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("openapi_public_enabled" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_data_redaction_disabled():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        data_redaction_enabled=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("data_redaction_enabled" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_workflow_draft_execution_in_production():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        workflow_allow_draft_execution=True,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("workflow_allow_draft_execution" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_workflow_latest_subworkflow_in_production():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        workflow_allow_latest_subworkflow_in_production=True,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("workflow_allow_latest_subworkflow" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_tool_system_env_allow_all_in_production():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        tool_system_env_allow_all=True,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("tool_system_env_allow_all" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_trivial_database_password():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://postgres:postgres@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("database_url" in x.lower() and "trivial" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_trivial_execution_kernel_password():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        execution_kernel_db_url="postgresql+asyncpg://postgres:postgres@localhost:5432/ek",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("EXECUTION_KERNEL_DB_URL" in x and "trivial" in x.lower() for x in issues)


def test_validate_production_security_guardrails_requires_trusted_hosts():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("trusted_hosts" in x.lower() for x in issues)


def test_validate_production_security_guardrails_blocks_redis_without_url():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=True,
        event_bus_backend="redis",
        event_bus_redis_url="",
        event_bus_strict_startup=True,
    )
    issues = validate_production_security_guardrails(s)
    assert any("event_bus_redis_url" in x for x in issues)


def test_validate_production_security_guardrails_blocks_kafka_without_bootstrap():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=True,
        event_bus_backend="kafka",
        event_bus_kafka_bootstrap_servers="",
        event_bus_strict_startup=True,
    )
    issues = validate_production_security_guardrails(s)
    assert any("event_bus_kafka_bootstrap_servers" in x for x in issues)


def test_validate_production_security_guardrails_blocks_event_bus_without_strict_startup():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=True,
        event_bus_backend="redis",
        event_bus_redis_url="redis://redis:6379/1",
        event_bus_strict_startup=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("event_bus_strict_startup" in x.lower() for x in issues)


def test_uvicorn_timeout_graceful_shutdown_seconds_optional():
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings().uvicorn_timeout_graceful_shutdown_seconds is None
    assert Settings(uvicorn_timeout_graceful_shutdown_seconds=40).uvicorn_timeout_graceful_shutdown_seconds == 40
    with pytest.raises(ValidationError):
        Settings(uvicorn_timeout_graceful_shutdown_seconds=0)


def test_settings_uvicorn_proxy_headers_defaults():
    from config.settings import Settings

    s = Settings()
    assert s.uvicorn_proxy_headers is True
    assert s.uvicorn_forwarded_allow_ips == ""


def test_settings_uvicorn_resilience_fields_optional():
    from config.settings import Settings

    s = Settings()
    assert s.uvicorn_limit_concurrency is None
    assert s.uvicorn_limit_max_requests is None
    assert s.uvicorn_server_header is True
    assert s.uvicorn_h11_max_incomplete_event_size is None
    assert s.uvicorn_access_log is True
    assert s.uvicorn_backlog is None
    assert s.uvicorn_ws_max_size is None
    assert s.uvicorn_limit_max_requests_jitter is None
    assert s.uvicorn_date_header is True
    assert s.uvicorn_ws_ping_interval_seconds is None
    assert s.uvicorn_ws_ping_timeout_seconds is None
    assert s.uvicorn_timeout_worker_healthcheck_seconds is None


def test_log_format_must_be_text_or_json():
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings(log_format="JSON").log_format == "json"
    with pytest.raises(ValidationError):
        Settings(log_format="yaml")


def test_uvicorn_timeout_keep_alive_seconds_optional():
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings().uvicorn_timeout_keep_alive_seconds is None
    assert Settings(uvicorn_timeout_keep_alive_seconds=75).uvicorn_timeout_keep_alive_seconds == 75
    with pytest.raises(ValidationError):
        Settings(uvicorn_timeout_keep_alive_seconds=0)


def test_validate_production_security_guardrails_requires_json_logs_when_not_debug():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="text",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("log_format" in x for x in issues)


def test_validate_production_security_guardrails_blocks_audit_root_prefix():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
        audit_log_enabled=True,
        audit_log_path_prefixes="/",
    )
    issues = validate_production_security_guardrails(s)
    assert any("audit_log_path_prefixes" in x and "/" in x for x in issues)


def test_validate_production_security_guardrails_warns_health_ready_strict_without_event_bus():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=True,
    )
    issues = validate_production_security_guardrails(s)
    assert any("health_ready_strict_event_bus" in x for x in issues)


def test_validate_production_security_guardrails_warns_health_ready_strict_inference_without_cache():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
        inference_cache_enabled=False,
        health_ready_strict_inference_redis=True,
    )
    issues = validate_production_security_guardrails(s)
    assert any("health_ready_strict_inference_redis" in x for x in issues)


def test_validate_production_security_guardrails_warns_health_ready_strict_arl_without_redis_url():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
        inference_cache_enabled=False,
        health_ready_strict_inference_redis=False,
        api_rate_limit_redis_url="",
        health_ready_strict_api_rate_limit_redis=True,
    )
    issues = validate_production_security_guardrails(s)
    assert any("health_ready_strict_api_rate_limit_redis" in x for x in issues)


def test_validate_production_security_guardrails_requires_database_url():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("database_url" in x for x in issues)


def test_validate_production_security_guardrails_blocks_sqlite_in_production():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="sqlite:///./app.db",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("SQLite" in x for x in issues)


def test_validate_production_security_guardrails_blocks_non_postgres_database_url():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="mysql+pymysql://u:p@db:3306/perilla",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("PostgreSQL" in x for x in issues)


def test_validate_production_security_guardrails_execution_kernel_db_url_sqlite():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        execution_kernel_db_url="sqlite+aiosqlite:///./ek.db",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("EXECUTION_KERNEL_DB_URL" in x and "SQLite" in x for x in issues)


def test_validate_production_security_guardrails_execution_kernel_db_url_non_postgres():
    import types as _types
    from config.settings import validate_production_security_guardrails

    s = _types.SimpleNamespace(
        debug=False,
        trusted_hosts="api.example.com",
        database_url="postgresql+psycopg2://u:p@localhost:5432/perilla",
        execution_kernel_db_url="mysql+pymysql://u:p@db:3306/ek",
        log_format="json",
        file_read_allowed_roots="./data",
        production_file_read_required_roots="./data",
        production_file_read_allowed_roots="./data,/app/data,/app/backend/data",
        cors_allowed_origins="https://example.com",
        tool_net_http_enabled=False,
        event_bus_enabled=False,
        health_ready_strict_event_bus=False,
    )
    issues = validate_production_security_guardrails(s)
    assert any("EXECUTION_KERNEL_DB_URL" in x and "PostgreSQL" in x for x in issues)


def test_settings_execution_kernel_db_url_field():
    from config.settings import Settings

    s = Settings(
        execution_kernel_db_url="postgresql+asyncpg://u:p@localhost:5432/ek",
    )
    assert "postgresql" in s.execution_kernel_db_url


def test_workflow_scheduler_max_concurrency_field_validation():
    import pytest
    from pydantic import ValidationError

    from config.settings import Settings

    s = Settings(workflow_scheduler_max_concurrency=32)
    assert s.workflow_scheduler_max_concurrency == 32
    with pytest.raises(ValidationError):
        Settings(workflow_scheduler_max_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(workflow_scheduler_max_concurrency=500)


def test_prometheus_metrics_path_validation():
    import pytest
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings(prometheus_metrics_path="/metrics/custom").prometheus_metrics_path == "/metrics/custom"
    with pytest.raises(ValidationError):
        Settings(prometheus_metrics_path="metrics")
    with pytest.raises(ValidationError):
        Settings(prometheus_metrics_path="/foo/../metrics")


def test_db_pool_timeout_seconds_field_validation():
    import pytest
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings(db_pool_timeout_seconds=45.5).db_pool_timeout_seconds == 45.5
    with pytest.raises(ValidationError):
        Settings(db_pool_timeout_seconds=0.5)
    with pytest.raises(ValidationError):
        Settings(db_pool_timeout_seconds=700)


def test_event_bus_ping_timeout_seconds_field_validation():
    import pytest
    from pydantic import ValidationError

    from config.settings import Settings

    assert Settings(event_bus_redis_ping_timeout_seconds=0.5).event_bus_redis_ping_timeout_seconds == 0.5
    with pytest.raises(ValidationError):
        Settings(event_bus_redis_ping_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(event_bus_redis_ping_timeout_seconds=200)
    with pytest.raises(ValidationError):
        Settings(event_bus_kafka_ping_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(event_bus_kafka_ping_timeout_seconds=500)


def test_security_guardrails_strict_default_true():
    from config.settings import Settings

    s = Settings()
    assert s.security_guardrails_strict is True


def test_verify_event_bus_startup_alignment_warns_kafka_missing(monkeypatch):
    from core.events import bus as bus_mod
    from core.events.bus import CompositeEventBus, InProcessEventBus
    from config.settings import settings
    import main as main_mod

    monkeypatch.setattr(settings, "event_bus_enabled", True)
    monkeypatch.setattr(settings, "event_bus_backend", "kafka")
    monkeypatch.setattr(settings, "event_bus_strict_startup", False)

    fake_bus = CompositeEventBus(InProcessEventBus())
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: fake_bus)

    warnings: list[str] = []

    def capture_warning(fmt: object, *args: object, **kwargs: object) -> None:
        if args and isinstance(fmt, str) and "%" in fmt:
            try:
                warnings.append(fmt % args)
            except Exception:
                warnings.append(str(fmt))
        else:
            warnings.append(str(fmt))

    monkeypatch.setattr(main_mod.logger, "warning", capture_warning)

    main_mod._verify_event_bus_startup_alignment()
    assert any("Kafka did not attach" in m for m in warnings)


def test_verify_event_bus_startup_alignment_raises_when_strict_kafka_missing(monkeypatch):
    import pytest

    from core.events import bus as bus_mod
    from core.events.bus import CompositeEventBus, InProcessEventBus
    from config.settings import settings
    import main as main_mod

    monkeypatch.setattr(settings, "event_bus_enabled", True)
    monkeypatch.setattr(settings, "event_bus_backend", "kafka")
    monkeypatch.setattr(settings, "event_bus_strict_startup", True)

    fake_bus = CompositeEventBus(InProcessEventBus())
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: fake_bus)

    with pytest.raises(RuntimeError, match="event_bus_strict_startup"):
        main_mod._verify_event_bus_startup_alignment()
