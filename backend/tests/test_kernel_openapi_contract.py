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

    toggle_post = paths["/api/system/kernel/toggle"]["post"]
    assert toggle_post["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/KernelToggleBody"
    toggle_200 = toggle_post["responses"]["200"]["content"]["application/json"]["schema"]
    assert toggle_200.get("oneOf")
    toggle_refs = {entry["$ref"] for entry in toggle_200["oneOf"]}
    assert toggle_refs == {
        "#/components/schemas/KernelToggleSuccessResponse",
        "#/components/schemas/KernelToggleErrorResponse",
    }
    assert set(schemas["KernelToggleSuccessResponse"].get("required") or []) == {"enabled", "note"}
    assert schemas["KernelToggleSuccessResponse"]["properties"]["success"]["const"] is True
    assert set(schemas["KernelToggleErrorResponse"].get("required") or []) == {"error"}
    assert schemas["KernelToggleErrorResponse"]["properties"]["success"]["const"] is False


def test_kernel_stats_response_matches_observability_get_stats() -> None:
    from core.agent_runtime.v2.observability import get_kernel_stats as obs_get_kernel_stats

    raw = obs_get_kernel_stats().get_stats()
    model = system_api.KernelStatsResponse.model_validate(raw)
    assert model.total_runs == raw["total_runs"]


def test_kernel_toggle_response_models_validate() -> None:
    ok = system_api.KernelToggleSuccessResponse.model_validate(
        {"success": True, "enabled": True, "note": "n"},
    )
    assert ok.enabled is True
    bad = system_api.KernelToggleErrorResponse.model_validate({"success": False, "error": "e"})
    assert bad.error == "e"


def test_openapi_kernel_optimization_endpoints_use_named_success_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}

    opt_get = paths["/api/system/kernel/optimization"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert opt_get.get("anyOf")
    assert {
        "#/components/schemas/OptimizationStatusUnavailableResponse",
        "#/components/schemas/OptimizationStatusReadyResponse",
    } == {x["$ref"] for x in opt_get["anyOf"]}

    rebuild = paths["/api/system/kernel/optimization/rebuild-snapshot"]["post"]
    rb_schema = rebuild["requestBody"]["content"]["application/json"]["schema"]
    if rb_schema.get("anyOf"):
        rb_refs = {item["$ref"] for item in rb_schema["anyOf"] if item.get("$ref")}
        assert "#/components/schemas/OptimizationRebuildBody" in rb_refs
    else:
        assert rb_schema["$ref"] == "#/components/schemas/OptimizationRebuildBody"
    rb_200 = rebuild["responses"]["200"]["content"]["application/json"]["schema"]
    assert rb_200.get("oneOf")
    assert {
        "#/components/schemas/OptimizationRebuildSuccessResponse",
        "#/components/schemas/OptimizationRebuildFailureResponse",
    } == {x["$ref"] for x in rb_200["oneOf"]}

    cfg = paths["/api/system/kernel/optimization/config"]["post"]
    assert cfg["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/OptimizationConfigUpdateBody"
    cfg_200 = cfg["responses"]["200"]["content"]["application/json"]["schema"]
    assert cfg_200.get("oneOf")
    assert {
        "#/components/schemas/OptimizationConfigUpdateSuccessResponse",
        "#/components/schemas/OptimizationConfigUpdateFailureResponse",
    } == {x["$ref"] for x in cfg_200["oneOf"]}

    imp = paths["/api/system/kernel/optimization/impact-report"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert imp.get("anyOf")
    assert {
        "#/components/schemas/OptimizationImpactErrorResponse",
        "#/components/schemas/OptimizationImpactOkResponse",
    } == {x["$ref"] for x in imp["anyOf"]}


def test_optimization_endpoints_adapter_missing_json(monkeypatch):
    import core.agent_runtime.v2.runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "get_kernel_adapter", lambda: None)
    client = _build_client()

    opt = client.get("/api/system/kernel/optimization")
    assert opt.status_code == 200
    assert opt.json() == {"enabled": False, "error": system_api.KERNEL_ADAPTER_NOT_INITIALIZED}

    impact = client.get("/api/system/kernel/optimization/impact-report")
    assert impact.status_code == 200
    assert impact.json() == {"error": system_api.KERNEL_ADAPTER_NOT_INITIALIZED}

    rebuild = client.post("/api/system/kernel/optimization/rebuild-snapshot", json={})
    assert rebuild.status_code == 200
    assert rebuild.json() == {"success": False, "error": system_api.KERNEL_ADAPTER_NOT_INITIALIZED}

    cfg = client.post("/api/system/kernel/optimization/config", json={})
    assert cfg.status_code == 200
    assert cfg.json()["success"] is False
    assert cfg.json()["error"] == system_api.KERNEL_ADAPTER_NOT_INITIALIZED


def test_kernel_toggle_http_success_and_missing_enabled(monkeypatch):
    import core.agent_runtime.v2.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "USE_EXECUTION_KERNEL", False)
    client = _build_client()

    missing = client.post("/api/system/kernel/toggle", json={})
    assert missing.status_code == 200
    assert missing.json() == {"success": False, "error": "Missing 'enabled' field"}

    applied = client.post("/api/system/kernel/toggle", json={"enabled": True})
    assert applied.status_code == 200
    body = applied.json()
    assert body["success"] is True
    assert body["enabled"] is True
    assert body["note"]
