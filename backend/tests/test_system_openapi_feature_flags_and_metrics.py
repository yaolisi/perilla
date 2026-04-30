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
