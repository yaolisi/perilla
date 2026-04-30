from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import system as system_api
from api.errors import register_error_handlers

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


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


def test_openapi_includes_roadmap_kpis_quality_metrics_and_phase_status() -> None:
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

    phase_get = paths["/api/system/roadmap/phases/status"]["get"]
    phase_ref = phase_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert phase_ref == "#/components/schemas/RoadmapPhaseStatusResponse"

    rps = schemas["RoadmapPhaseStatusResponse"]
    assert set(rps.get("required") or []) == {
        "snapshot",
        "north_star",
        "go_no_go",
        "go_no_go_reasons",
        "phase_gate",
    }
    assert rps["properties"]["north_star"]["$ref"] == "#/components/schemas/RoadmapNorthStarStatus"
    assert rps["properties"]["phase_gate"]["$ref"] == "#/components/schemas/RoadmapPhaseGateStatus"
    assert rps["properties"]["go_no_go"]["enum"] == ["go", "no_go"]

    assert set(schemas["RoadmapNorthStarStatus"].get("required") or []) == {"score", "passed", "reasons"}
    assert set(schemas["RoadmapPhaseGateStatus"].get("required") or []) == {
        "passed_count",
        "total_count",
        "score",
        "phases",
        "blocking_capabilities",
        "readiness_summary",
    }

    gates_item = paths["/api/system/roadmap/phase-gates"]
    assert set(gates_item.keys()) == {"post"}
    gates_post = gates_item["post"]
    assert gates_post["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/RoadmapGateUpdateBody"
    gates_ref = gates_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert gates_ref == "#/components/schemas/RoadmapPhaseGatesUpdateResponse"
    pg_resp = schemas["RoadmapPhaseGatesUpdateResponse"]
    assert set(pg_resp.get("required") or []) == {"phase_gates"}
    assert pg_resp["properties"]["success"]["const"] is True

    monthly = paths["/api/system/roadmap/monthly-review"]
    assert set(monthly.keys()) == {"get", "post"}
    monthly_get_ref = monthly["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert monthly_get_ref == "#/components/schemas/RoadmapMonthlyReviewListResponse"
    assert set(schemas["RoadmapMonthlyReviewListResponse"].get("required") or []) == {"count", "items", "meta"}

    monthly_post_ref = monthly["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert monthly_post_ref == "#/components/schemas/RoadmapMonthlyReviewCreateResponse"
    m_create = schemas["RoadmapMonthlyReviewCreateResponse"]
    assert set(m_create.get("required") or []) == {"review"}
    assert m_create["properties"]["success"]["const"] is True


def test_openapi_roadmap_paths_use_named_schema_for_json_200() -> None:
    client = _build_client()
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec.get("paths") or {}
    schemas = (spec.get("components") or {}).get("schemas") or {}
    roadmap_paths = sorted(p for p in paths if p.startswith("/api/system/roadmap"))
    assert roadmap_paths
    for path in roadmap_paths:
        path_item = paths[path]
        for method, op in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            ok = (op.get("responses") or {}).get("200")
            if not ok:
                continue
            app_json = (ok.get("content") or {}).get("application/json")
            if not app_json:
                continue
            schema = app_json.get("schema")
            assert isinstance(schema, dict) and "$ref" in schema, (
                f"{method.upper()} {path}: expected 200 application/json schema $ref, got {schema!r}"
            )
            ref = schema["$ref"]
            assert ref.startswith("#/components/schemas/")
            key = ref.rsplit("/", 1)[-1]
            assert key in schemas, f"{method.upper()} {path}: missing components.schemas.{key}"
