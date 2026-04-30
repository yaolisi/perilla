from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system as system_api
from api.errors import register_error_handlers


def _build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

    app.include_router(system_api.router)
    app.dependency_overrides[system_api.require_authenticated_platform_admin] = lambda: None
    app.dependency_overrides[system_api.require_platform_admin] = lambda: None
    return TestClient(app)


def test_openapi_feature_flags_and_hardware_metrics_use_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}

    ff_get = paths["/api/system/feature-flags"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ff_get == "#/components/schemas/FeatureFlagsReadResponse"

    ff_post = paths["/api/system/feature-flags"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ff_post == "#/components/schemas/FeatureFlagsUpdateResponse"

    metrics_ref = paths["/api/system/metrics"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert metrics_ref == "#/components/schemas/HardwareMetricsResponse"

    schemas = spec.get("components", {}).get("schemas") or {}
    assert set(schemas["FeatureFlagsReadResponse"].get("required") or []) == {"flags"}
    ff_up = schemas["FeatureFlagsUpdateResponse"]
    assert set(ff_up.get("required") or []) == {"flags"}
    assert ff_up["properties"]["success"]["const"] is True

    hm = schemas["HardwareMetricsResponse"]
    assert set(hm.get("required") or []) >= {"cpu_load", "gpu_usage", "uptime"}

    obs_ref = paths["/api/system/observability-summary"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert obs_ref == "#/components/schemas/ObservabilitySummaryResponse"
    assert set(schemas["ObservabilitySummaryResponse"].get("required") or []) == {
        "requests",
        "failed_requests",
        "failure_rate",
        "models_count",
        "total_latency_ms",
    }

    rt_ref = paths["/api/system/runtime-metrics"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert rt_ref == "#/components/schemas/RuntimeMetricsApiResponse"
    rt = schemas["RuntimeMetricsApiResponse"]
    assert set(rt.get("required") or []) >= {"summary", "by_priority_summary", "by_model", "priority_slo_panel"}


def test_observability_summary_and_runtime_metrics_http_smoke() -> None:
    client = _build_client()
    obs = client.get("/api/system/observability-summary")
    assert obs.status_code == 200
    body = obs.json()
    assert set(body.keys()) >= {"requests", "failure_rate", "models_count"}

    rt = client.get("/api/system/runtime-metrics")
    assert rt.status_code == 200
    data = rt.json()
    assert "summary" in data and "by_model" in data and "priority_slo_panel" in data
