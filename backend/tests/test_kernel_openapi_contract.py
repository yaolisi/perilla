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


def test_openapi_kernel_status_stats_reset_use_named_schemas() -> None:
    client = _build_client()
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec.get("paths") or {}

    status_ref = paths["/api/system/kernel/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert status_ref == "#/components/schemas/KernelStatusResponse"

    stats_ref = paths["/api/system/kernel/stats"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert stats_ref == "#/components/schemas/KernelStatsResponse"

    reset_ref = paths["/api/system/kernel/stats/reset"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reset_ref == "#/components/schemas/KernelStatsResetResponse"

    schemas = spec.get("components", {}).get("schemas") or {}
    assert set(schemas["KernelStatusResponse"].get("required") or []) == {"enabled", "can_toggle", "description"}
    ks = schemas["KernelStatsResponse"]
    assert set(ks.get("required") or []) >= {
        "total_runs",
        "kernel_runs",
        "plan_based_runs",
        "kernel_success_rate",
        "kernel_fallback_rate",
        "step_fail_rate",
        "replan_trigger_rate",
        "avg_duration_ms",
    }


def test_kernel_stats_response_matches_observability_get_stats() -> None:
    from core.agent_runtime.v2.observability import get_kernel_stats as obs_get_kernel_stats

    raw = obs_get_kernel_stats().get_stats()
    model = system_api.KernelStatsResponse.model_validate(raw)
    assert model.total_runs == raw["total_runs"]
