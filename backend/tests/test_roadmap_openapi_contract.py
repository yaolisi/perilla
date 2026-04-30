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


def test_openapi_includes_roadmap_kpis_and_quality_metrics() -> None:
    client = _build_client()
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec.get("paths") or {}
    assert "/api/system/roadmap/kpis" in paths
    assert "get" in paths["/api/system/roadmap/kpis"]
    assert "post" in paths["/api/system/roadmap/kpis"]
    assert "/api/system/roadmap/quality-metrics" in paths
    assert "get" in paths["/api/system/roadmap/quality-metrics"]
    assert "post" in paths["/api/system/roadmap/quality-metrics"]

    kpis_get = paths["/api/system/roadmap/kpis"]["get"]
    schema_ref = kpis_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/RoadmapKpisReadResponse"

    kpis_post = paths["/api/system/roadmap/kpis"]["post"]
    post_ref = kpis_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert post_ref == "#/components/schemas/RoadmapKpisUpdateResponse"

    qm_get = paths["/api/system/roadmap/quality-metrics"]["get"]
    qm_get_ref = qm_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert qm_get_ref == "#/components/schemas/RoadmapQualityMetricsReadResponse"

    qm_post = paths["/api/system/roadmap/quality-metrics"]["post"]
    qm_post_ref = qm_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert qm_post_ref == "#/components/schemas/RoadmapQualityMetricsUpdateResponse"

    schemas = spec.get("components", {}).get("schemas") or {}
    assert set(schemas["RoadmapKpisReadResponse"].get("required") or []) == {"kpis"}
    kpi_update = schemas["RoadmapKpisUpdateResponse"]
    assert set(kpi_update.get("required") or []) == {"kpis"}
    assert kpi_update["properties"]["success"]["const"] is True
    qm_required = set(schemas["RoadmapQualityMetricsReadResponse"].get("required") or [])
    assert {"quality_metrics", "explicit_metric_keys_tracked"} <= qm_required
