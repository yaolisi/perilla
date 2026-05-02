import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import settings
from middleware.gzip_selective import SelectiveGZipMiddleware
from middleware.rate_limit import InMemoryRateLimitMiddleware
from middleware.request_trace import RequestTraceMiddleware
from middleware.csrf_protection import CSRFMiddleware
from middleware.sensitive_data_redaction import SensitiveDataRedactionMiddleware
from middleware.tenant_context import TenantContextMiddleware
from middleware.tenant_key_binding import TenantApiKeyBindingMiddleware
from tests.helpers import make_fastapi_app_router_only


def create_app_for_test(limit: int = 2) -> FastAPI:
    app = make_fastapi_app_router_only()
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


def test_selective_gzip_skips_metrics_and_health_probe(monkeypatch):
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/metrics")
    app = FastAPI()
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1)

    @app.get("/metrics")
    def _metrics():
        return "x" * 800

    @app.get("/api/health")
    def _health():
        return {"ok": True}

    @app.get("/big")
    def _big():
        return "y" * 800

    client = TestClient(app)
    m = client.get("/metrics", headers={"Accept-Encoding": "gzip"})
    assert m.headers.get("content-encoding") != "gzip"
    h = client.get("/api/health", headers={"Accept-Encoding": "gzip"})
    assert h.headers.get("content-encoding") != "gzip"
    b = client.get("/big", headers={"Accept-Encoding": "gzip"})
    assert b.headers.get("content-encoding") == "gzip"


def test_request_trace_quiet_logs_for_metrics_and_health(monkeypatch):
    import middleware.request_trace as rt_mod

    infos: list[int] = []
    debugs: list[int] = []

    monkeypatch.setattr(rt_mod.logger, "info", lambda *a, **k: infos.append(1))
    monkeypatch.setattr(rt_mod.logger, "debug", lambda *a, **k: debugs.append(1))
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/metrics")

    app = FastAPI()
    app.add_middleware(RequestTraceMiddleware, header_name="X-Request-Id")

    @app.get("/metrics")
    def _metrics():
        return "#\n"

    @app.get("/api/health")
    def _health():
        return {"status": "healthy"}

    @app.get("/ok")
    def _ok():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/metrics").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/ok").status_code == 200
    assert len(infos) == 1
    assert len(debugs) >= 2


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
    assert blocked.headers.get("Retry-After") == "60"
    body = blocked.json()
    assert body["error"] == "rate_limit_exceeded"
    assert body["identity_type"] == "api_key"


def test_rate_limit_events_path_uses_stricter_window_and_isolated_from_global():
    """api_rate_limit_events_requests > 0：仅 /api/events* 使用 ev: 计数键，与其它路径配额独立。"""
    app = FastAPI()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=100,
        window_seconds=60,
        api_key_header="X-Api-Key",
        events_requests_per_window=2,
        events_path_prefix="/api/events",
    )

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/api/events/smoke")
    def ev():
        return {"events": True}

    client = TestClient(app)
    h = {"X-Api-Key": "k1"}
    assert client.get("/api/events/smoke", headers=h).status_code == 200
    assert client.get("/api/events/smoke", headers=h).status_code == 200
    blocked_ev = client.get("/api/events/smoke", headers=h)
    assert blocked_ev.status_code == 429
    assert blocked_ev.json()["limit"] == 2
    # 全局桶仍空，非 events 路径放行
    assert client.get("/ok", headers=h).status_code == 200


def test_rate_limit_blocked_observes_prometheus(monkeypatch):
    from core.observability.prometheus_metrics import get_prometheus_business_metrics

    called: list[tuple[str, str, str]] = []

    def _spy(*, reason: str, identity_type: str, backend: str) -> None:
        called.append((reason, identity_type, backend))

    m = get_prometheus_business_metrics()
    monkeypatch.setattr(m, "observe_rate_limit_blocked", _spy)

    app = create_app_for_test(limit=2)
    client = TestClient(app)
    headers = {"X-Api-Key": "metric-key"}
    assert client.get("/ok", headers=headers).status_code == 200
    assert client.get("/ok", headers=headers).status_code == 200
    blocked = client.get("/ok", headers=headers)
    assert blocked.status_code == 429
    assert called == [("window", "api_key", "memory")]


def test_rate_limit_redis_fail_closed_returns_503(monkeypatch):
    monkeypatch.setattr(settings, "api_rate_limit_redis_fail_closed", True)

    class BrokenRedis:
        async def incr(self, key: str) -> int:
            raise RuntimeError("redis down")

        async def expire(self, key: str, ttl: int) -> None:
            pass

    monkeypatch.setattr(
        "core.redis_client_factory.create_async_redis_client",
        lambda url, decode_responses=True: BrokenRedis(),
    )

    app = FastAPI()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=10,
        window_seconds=60,
        api_key_header="X-Api-Key",
        max_concurrent_per_user=5,
        redis_url="redis://127.0.0.1:6379/15",
    )

    @app.get("/ok")
    def _ok():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ok", headers={"X-Api-Key": "k"})
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"
    body = r.json()
    assert body.get("error") == "rate_limit_backend_unavailable"


def test_rate_limit_redis_backend_fixed_window(monkeypatch):
    """配置 Redis URL 时使用 INCR 固定窗口；与进程内路径行为对齐（阈值相同）。"""

    class FakeRedis:
        def __init__(self) -> None:
            self.ints: dict[str, int] = {}

        async def incr(self, key: str) -> int:
            self.ints[key] = self.ints.get(key, 0) + 1
            return self.ints[key]

        async def expire(self, key: str, ttl: int) -> None:
            _ = (key, ttl)

        async def decr(self, key: str) -> int:
            self.ints[key] = self.ints.get(key, 0) - 1
            return self.ints[key]

        async def set(self, key: str, val: int) -> None:
            self.ints[key] = int(val)

        async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> int:
            ka = list(keys_and_args)
            key = str(ka[0])
            max_c = int(ka[1])
            _ttl = int(ka[2])
            cur = self.ints.get(key, 0) + 1
            self.ints[key] = cur
            if cur > max_c:
                self.ints[key] = cur - 1
                return 0
            return 1

    monkeypatch.setattr(
        "core.redis_client_factory.create_async_redis_client",
        lambda url, decode_responses=True: FakeRedis(),
    )

    app = FastAPI()
    app.add_middleware(
        InMemoryRateLimitMiddleware,
        requests_per_window=2,
        window_seconds=60,
        api_key_header="X-Api-Key",
        max_concurrent_per_user=10,
        redis_url="redis://127.0.0.1:6379/15",
        redis_key_prefix="t:rl",
    )

    @app.get("/ok")
    def _ok():
        return {"ok": True}

    client = TestClient(app)
    headers = {"X-Api-Key": "redis-k"}
    assert client.get("/ok", headers=headers).status_code == 200
    assert client.get("/ok", headers=headers).status_code == 200
    blocked = client.get("/ok", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate_limit_exceeded"


def test_rate_limit_skips_health_checks():
    app = create_app_for_test(limit=1)
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_rate_limit_skips_prometheus_metrics_path(monkeypatch):
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/prom/metrics")
    app = create_app_for_test(limit=1)

    @app.get("/prom/metrics")
    def _metrics():
        return "# ok\n"

    client = TestClient(app)
    headers = {"X-Api-Key": "scraper"}
    for _ in range(5):
        assert client.get("/prom/metrics", headers=headers).status_code == 200


def test_sensitive_redaction_skips_prometheus_metrics_path(monkeypatch):
    import middleware.sensitive_data_redaction as red_mod

    monkeypatch.setattr(settings, "data_redaction_enabled", True)
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/metrics")

    calls: list[int] = []

    def track_tokens() -> list[str]:
        calls.append(1)
        return ["token"]

    monkeypatch.setattr(red_mod, "_load_sensitive_tokens", track_tokens)

    app = FastAPI()
    app.add_middleware(SensitiveDataRedactionMiddleware)

    @app.get("/metrics")
    def _m():
        return "# ok\n"

    @app.get("/other")
    def _other():
        return {"a": 1}

    client = TestClient(app)
    assert client.get("/metrics").status_code == 200
    assert calls == []
    assert client.get("/other").status_code == 200
    assert calls == [1]


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

        app = make_fastapi_app_router_only()
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

        app = make_fastapi_app_router_only()
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


def test_csrf_exempts_prometheus_metrics_path_for_mutations(monkeypatch):
    """自定义 metrics 路径与 ops_paths 一致，非安全方法也不强制双提交（与抓取/自动化一致）。"""
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/m2")
    monkeypatch.setattr(settings, "csrf_enabled", True)
    monkeypatch.setattr(settings, "csrf_cookie_name", "csrf_token")
    monkeypatch.setattr(settings, "csrf_header_name", "X-CSRF-Token")
    app = make_fastapi_app_router_only()
    app.add_middleware(CSRFMiddleware)

    @app.post("/m2")
    def _ingest():
        return {"ingested": True}

    c = TestClient(app)
    r = c.post("/m2", json={})
    assert r.status_code == 200
    assert r.json().get("ingested") is True


def test_csrf_blocks_mutation_without_token_header():
    prev_enabled = settings.csrf_enabled
    prev_cookie_name = settings.csrf_cookie_name
    prev_header_name = settings.csrf_header_name
    try:
        settings.csrf_enabled = True
        settings.csrf_cookie_name = "csrf_token"
        settings.csrf_header_name = "X-CSRF-Token"

        app = make_fastapi_app_router_only()
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

        app = make_fastapi_app_router_only()
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

        app = make_fastapi_app_router_only()
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


def test_http_request_size_limit_rejects_oversized_body(monkeypatch):
    from middleware.request_size_limit import HttpRequestSizeLimitMiddleware

    monkeypatch.setattr(settings, "http_max_request_body_bytes", 10)
    app = FastAPI()
    app.add_middleware(HttpRequestSizeLimitMiddleware)

    @app.post("/p")
    def _p():
        return {"ok": True}

    c = TestClient(app)
    assert c.post("/p", content=b"12345678901").status_code == 413
    assert c.post("/p", content=b"1234567890").status_code == 200


def test_http_request_size_limit_disabled_when_zero(monkeypatch):
    from middleware.request_size_limit import HttpRequestSizeLimitMiddleware

    monkeypatch.setattr(settings, "http_max_request_body_bytes", 0)
    app = FastAPI()
    app.add_middleware(HttpRequestSizeLimitMiddleware)

    @app.post("/p")
    def _p():
        return {"ok": True}

    c = TestClient(app)
    assert c.post("/p", content=b"x" * 10000).status_code == 200


def test_http_request_size_limit_skips_ops_paths(monkeypatch):
    from middleware.request_size_limit import HttpRequestSizeLimitMiddleware

    monkeypatch.setattr(settings, "http_max_request_body_bytes", 10)
    monkeypatch.setattr(settings, "prometheus_metrics_path", "/metrics")
    app = FastAPI()
    app.add_middleware(HttpRequestSizeLimitMiddleware)

    @app.post("/metrics")
    def _m():
        return {"ok": True}

    @app.post("/api/health/ready")
    def _r():
        return {"ok": True}

    c = TestClient(app)
    big = b"x" * 1000
    assert c.post("/metrics", content=big).status_code == 200
    assert c.post("/api/health/ready", content=big).status_code == 200


@pytest.mark.asyncio
async def test_http_request_size_limit_chunked_without_content_length_rejects(monkeypatch):
    import httpx

    from middleware.request_size_limit import HttpRequestSizeLimitMiddleware

    monkeypatch.setattr(settings, "http_max_request_body_bytes", 10)
    app = FastAPI()
    app.add_middleware(HttpRequestSizeLimitMiddleware)

    @app.post("/p")
    def _p():
        return {"ok": True}

    async def oversized():
        yield b"a" * 6
        yield b"b" * 6

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/p", content=oversized())
    assert r.status_code == 413
    body = r.json()
    assert body.get("detail") == "request body too large"
    assert body.get("limit_bytes") == 10


@pytest.mark.asyncio
async def test_http_request_size_limit_chunked_within_limit_ok(monkeypatch):
    import httpx

    from middleware.request_size_limit import HttpRequestSizeLimitMiddleware

    monkeypatch.setattr(settings, "http_max_request_body_bytes", 20)
    app = FastAPI()
    app.add_middleware(HttpRequestSizeLimitMiddleware)

    @app.post("/p")
    def _p():
        return {"ok": True}

    async def body12():
        yield b"a" * 6
        yield b"b" * 6

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/p", content=body12())
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_security_headers_added_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "security_headers_enabled", True)
    app = FastAPI()
    from middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def _x():
        return {"ok": True}

    r = TestClient(app).get("/x")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_security_headers_not_added_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "security_headers_enabled", False)
    app = FastAPI()
    from middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def _x():
        return {"ok": True}

    r = TestClient(app).get("/x")
    assert r.headers.get("X-Frame-Options") is None


def test_security_headers_omit_frame_when_empty(monkeypatch):
    monkeypatch.setattr(settings, "security_headers_enabled", True)
    monkeypatch.setattr(settings, "security_headers_x_frame_options", "")
    app = FastAPI()
    from middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def _x():
        return {"ok": True}

    r = TestClient(app).get("/x")
    assert r.headers.get("X-Frame-Options") is None
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_security_headers_hsts_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "security_headers_enabled", True)
    monkeypatch.setattr(
        settings,
        "security_headers_strict_transport_security",
        "max-age=63072000; includeSubDomains",
    )
    app = FastAPI()
    from middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def _x():
        return {"ok": True}

    r = TestClient(app).get("/x")
    assert r.headers.get("Strict-Transport-Security") == "max-age=63072000; includeSubDomains"
