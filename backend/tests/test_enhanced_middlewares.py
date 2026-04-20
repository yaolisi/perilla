from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.rate_limit import InMemoryRateLimitMiddleware
from middleware.request_trace import RequestTraceMiddleware
from middleware.csrf_protection import CSRFMiddleware
from middleware.tenant_context import TenantContextMiddleware
from middleware.tenant_key_binding import TenantApiKeyBindingMiddleware


def create_app_for_test(limit: int = 2) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware, header_name="X-Request-Id")
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=limit,
        window_seconds=60,
        api_key_header="X-Api-Key",
    )

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"status": "healthy"}

    return app


def test_request_trace_injects_headers():
    app = create_app_for_test(limit=10)
    client = TestClient(app)
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id")
    assert resp.headers.get("X-Trace-Id")
    assert resp.headers.get("X-Response-Time-Ms") is not None


def test_request_trace_reuses_incoming_request_id():
    app = create_app_for_test(limit=10)
    client = TestClient(app)
    resp = client.get("/ok", headers={"X-Request-Id": "req-123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "req-123"


def test_rate_limit_blocks_after_threshold():
    app = create_app_for_test(limit=2)
    client = TestClient(app)
    headers = {"X-Api-Key": "abc"}
    assert client.get("/ok", headers=headers).status_code == 200
    assert client.get("/ok", headers=headers).status_code == 200
    blocked = client.get("/ok", headers=headers)
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"] == "rate_limit_exceeded"
    assert body["identity_type"] == "api_key"


def test_rate_limit_skips_health_checks():
    app = create_app_for_test(limit=1)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_request_trace_invalid_request_id_fallback_to_uuid():
    app = create_app_for_test(limit=10)
    client = TestClient(app)
    polluted = "bad\r\nInjected: x"
    resp = client.get("/ok", headers={"X-Request-Id": polluted})
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-Id")
    assert rid
    assert "Injected" not in rid
    assert "\r" not in rid
    assert "\n" not in rid


def test_tenant_key_binding_blocks_unmapped_key():
    prev_enabled = settings.tenant_api_key_binding_enabled
    prev_mapping = settings.tenant_api_key_tenants_json
    prev_default_tenant = settings.tenant_default_id
    try:
        settings.tenant_api_key_binding_enabled = True
        settings.tenant_api_key_tenants_json = '{"k-a":["tenant-a"]}'
        settings.tenant_default_id = "default"

        app = FastAPI()
        app.add_middleware(TenantContextMiddleware)
        app.add_middleware(TenantApiKeyBindingMiddleware)

        @app.get("/api/v1/workflows/w1")
        def read_workflow():
            return {"ok": True}

        client = TestClient(app)
        denied = client.get(
            "/api/v1/workflows/w1",
            headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-b"},
        )
        assert denied.status_code == 403

        allowed = client.get(
            "/api/v1/workflows/w1",
            headers={"X-Api-Key": "k-a", "X-Tenant-Id": "tenant-a"},
        )
        assert allowed.status_code == 200
    finally:
        settings.tenant_api_key_binding_enabled = prev_enabled
        settings.tenant_api_key_tenants_json = prev_mapping
        settings.tenant_default_id = prev_default_tenant


def test_csrf_issues_cookie_and_header_on_safe_request():
    prev_enabled = settings.csrf_enabled
    prev_cookie_name = settings.csrf_cookie_name
    prev_header_name = settings.csrf_header_name
    try:
        settings.csrf_enabled = True
        settings.csrf_cookie_name = "csrf_token"
        settings.csrf_header_name = "X-CSRF-Token"

        app = FastAPI()
        app.add_middleware(CSRFMiddleware)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        c = TestClient(app)
        resp = c.get("/ok")
        assert resp.status_code == 200
        assert resp.headers.get("X-CSRF-Token")
        assert c.cookies.get("csrf_token")
    finally:
        settings.csrf_enabled = prev_enabled
        settings.csrf_cookie_name = prev_cookie_name
        settings.csrf_header_name = prev_header_name


def test_csrf_blocks_mutation_without_token_header():
    prev_enabled = settings.csrf_enabled
    prev_cookie_name = settings.csrf_cookie_name
    prev_header_name = settings.csrf_header_name
    try:
        settings.csrf_enabled = True
        settings.csrf_cookie_name = "csrf_token"
        settings.csrf_header_name = "X-CSRF-Token"

        app = FastAPI()
        app.add_middleware(CSRFMiddleware)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.post("/mutate")
        def mutate():
            return {"ok": True}

        c = TestClient(app)
        # prime csrf cookie/token with a safe request
        assert c.get("/ok").status_code == 200
        denied = c.post("/mutate")
        assert denied.status_code == 403
    finally:
        settings.csrf_enabled = prev_enabled
        settings.csrf_cookie_name = prev_cookie_name
        settings.csrf_header_name = prev_header_name


def test_csrf_blocks_when_token_mismatch():
    prev_enabled = settings.csrf_enabled
    prev_cookie_name = settings.csrf_cookie_name
    prev_header_name = settings.csrf_header_name
    try:
        settings.csrf_enabled = True
        settings.csrf_cookie_name = "csrf_token"
        settings.csrf_header_name = "X-CSRF-Token"

        app = FastAPI()
        app.add_middleware(CSRFMiddleware)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.post("/mutate")
        def mutate():
            return {"ok": True}

        c = TestClient(app)
        assert c.get("/ok").status_code == 200
        denied = c.post("/mutate", headers={"X-CSRF-Token": "wrong-token"})
        assert denied.status_code == 403
    finally:
        settings.csrf_enabled = prev_enabled
        settings.csrf_cookie_name = prev_cookie_name
        settings.csrf_header_name = prev_header_name


def test_csrf_allows_when_cookie_and_header_match():
    prev_enabled = settings.csrf_enabled
    prev_cookie_name = settings.csrf_cookie_name
    prev_header_name = settings.csrf_header_name
    try:
        settings.csrf_enabled = True
        settings.csrf_cookie_name = "csrf_token"
        settings.csrf_header_name = "X-CSRF-Token"

        app = FastAPI()
        app.add_middleware(CSRFMiddleware)

        @app.get("/ok")
        def ok():
            return {"ok": True}

        @app.post("/mutate")
        def mutate():
            return {"ok": True}

        c = TestClient(app)
        assert c.get("/ok").status_code == 200
        token = c.cookies.get("csrf_token")
        assert token
        allowed = c.post("/mutate", headers={"X-CSRF-Token": token})
        assert allowed.status_code == 200
    finally:
        settings.csrf_enabled = prev_enabled
        settings.csrf_cookie_name = prev_cookie_name
        settings.csrf_header_name = prev_header_name
