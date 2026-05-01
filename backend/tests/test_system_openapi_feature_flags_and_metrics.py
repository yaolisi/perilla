from __future__ import annotations

from fastapi.testclient import TestClient

from api import system as system_api

from tests.helpers import make_fastapi_app_router_only


def _build_client() -> TestClient:
    app = make_fastapi_app_router_only(system_api)

    @app.middleware("http")
    async def _inject_test_user(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user_id = request.headers.get("X-User-Id")
        return await call_next(request)

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

    sbm = "#/components/schemas/SystemStringBoolMap"
    assert schemas["FeatureFlagsReadResponse"]["properties"]["flags"]["$ref"] == sbm
    assert schemas["FeatureFlagsUpdateResponse"]["properties"]["flags"]["$ref"] == sbm

    jmap = "#/components/schemas/SystemJsonMap"
    for key in ("summary", "by_priority_summary", "by_model", "priority_slo_panel"):
        assert schemas["RuntimeMetricsApiResponse"]["properties"][key]["$ref"] == jmap

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


def test_openapi_engine_browse_and_inference_cache_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}

    eng = paths["/api/system/engine/reload"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert eng == "#/components/schemas/EngineReloadResponse"

    br = paths["/api/system/browse-directory"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert br == "#/components/schemas/BrowseDirectoryResponse"

    stats_ref = paths["/api/system/inference/cache/stats"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert stats_ref == "#/components/schemas/InferenceCacheStatsResponse"

    ch_ref = paths["/api/system/inference/cache/clear/challenge"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ch_ref == "#/components/schemas/InferenceCacheClearChallengeResponse"

    clr_ref = paths["/api/system/inference/cache/clear"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert clr_ref == "#/components/schemas/InferenceCacheClearResultResponse"


def test_openapi_storage_readiness_and_queue_summary() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    sr_ref = paths["/api/system/storage-readiness"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert sr_ref == "#/components/schemas/StorageReadinessResponse"
    assert set(schemas["StorageReadinessResponse"].get("required") or []) == {"backend", "level", "advice"}

    qs_ref = paths["/api/system/queue-summary"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert qs_ref == "#/components/schemas/QueueSummaryResponse"
    assert set(schemas["QueueSummaryResponse"].get("required") or []) == {
        "workflow",
        "image_generation",
        "runtime",
        "total_load",
    }

    sr = client.get("/api/system/storage-readiness")
    assert sr.status_code == 200
    assert set(sr.json().keys()) == {"backend", "level", "advice"}

    qs = client.get("/api/system/queue-summary")
    assert qs.status_code == 200
    body = qs.json()
    assert body["workflow"]["running"] >= 0
    assert body["total_load"] >= 0


def test_openapi_event_bus_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    st_ref = paths["/api/system/event-bus/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert st_ref == "#/components/schemas/EventBusRuntimeStatusResponse"
    assert set(schemas["EventBusRuntimeStatusResponse"].get("required") or []) == {"dlq_size"}

    dlq_ref = paths["/api/system/event-bus/dlq"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert dlq_ref == "#/components/schemas/EventBusDlqListResponse"
    assert set(schemas["EventBusDlqListResponse"].get("required") or []) == {"count", "items"}

    clr_ref = paths["/api/system/event-bus/dlq/clear"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert clr_ref == "#/components/schemas/EventBusDlqClearResponse"
    clr = schemas["EventBusDlqClearResponse"]
    assert set(clr.get("required") or []) == {"cleared"}
    assert clr["properties"]["success"]["const"] is True

    rp_ref = paths["/api/system/event-bus/dlq/replay"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert rp_ref == "#/components/schemas/EventBusDlqReplayResponse"
    replay = schemas["EventBusDlqReplayResponse"]
    assert set(replay.get("required") or []) >= {"dry_run", "candidate", "replayed", "failed", "grouped"}
    grouped_prop = replay["properties"]["grouped"]
    assert grouped_prop.get("additionalProperties", {}).get("$ref") == "#/components/schemas/EventBusDlqReplayGroupedBucket"

    status_b = client.get("/api/system/event-bus/status").json()
    assert status_b.get("dlq_size") is not None and "published_total" in status_b

    dlq_b = client.get("/api/system/event-bus/dlq").json()
    assert dlq_b["count"] >= 0 and isinstance(dlq_b["items"], list)

    jmap = "#/components/schemas/SystemJsonMap"
    jrec = "#/components/schemas/SystemJsonRecord"
    assert schemas["EventBusRuntimeStatusResponse"]["properties"]["per_event_type"]["$ref"] == jmap
    assert schemas["EventBusDlqListResponse"]["properties"]["items"]["items"]["$ref"] == jrec


def test_openapi_system_config_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    cfg_get = paths["/api/system/config"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cfg_get == "#/components/schemas/SystemConfigReadResponse"
    assert set(schemas["SystemConfigReadResponse"].get("required") or []) == {
        "ollama_base_url",
        "localai_base_url",
        "textgen_webui_base_url",
        "app_name",
        "version",
        "local_model_directory",
        "settings",
        "mcp_http_emit_server_push_events_effective",
    }

    cfg_post = paths["/api/system/config"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cfg_post == "#/components/schemas/SystemConfigUpdateResponse"
    assert schemas["SystemConfigUpdateResponse"]["properties"]["success"]["const"] is True

    sch_ref = paths["/api/system/config/schema"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert sch_ref == "#/components/schemas/SystemConfigSchemaResponse"
    sch = schemas["SystemConfigSchemaResponse"]
    assert set(sch.get("required") or []) == {"allowed_keys", "schema_hints", "query_examples"}
    assert "examples" in sch["properties"]
    jmap = "#/components/schemas/SystemJsonMap"
    assert schemas["SystemConfigReadResponse"]["properties"]["settings"]["$ref"] == jmap
    hints_prop = sch["properties"]["schema_hints"]
    assert hints_prop["additionalProperties"]["$ref"] == jmap
    ex_any = sch["properties"]["examples"]["anyOf"]
    assert ex_any[0]["$ref"] == jmap

    body = client.get("/api/system/config").json()
    assert body["settings"] is not None
    assert isinstance(body["mcp_http_emit_server_push_events_effective"], bool)


def test_openapi_plugins_and_market_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    pl_ref = paths["/api/system/plugins"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert pl_ref == "#/components/schemas/PluginListResponse"
    assert set(schemas["PluginListResponse"].get("required") or []) == {"count", "plugins"}
    jrec = "#/components/schemas/SystemJsonRecord"
    assert schemas["PluginListResponse"]["properties"]["plugins"]["items"]["$ref"] == jrec

    for subpath, schema_name in (
        ("/api/system/plugins/register", "PluginSimpleOkResponse"),
        ("/api/system/plugins/unregister", "PluginSimpleOkResponse"),
        ("/api/system/plugins/reload", "PluginSimpleOkResponse"),
        ("/api/system/plugins/default", "PluginSimpleOkResponse"),
    ):
        ref = paths[subpath]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref == f"#/components/schemas/{schema_name}"

    mkt_ref = paths["/api/system/plugins/market"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert mkt_ref == "#/components/schemas/PluginMarketPackageListResponse"
    assert schemas["PluginMarketPackageListResponse"]["properties"]["items"]["items"]["$ref"] == jrec

    pub_ref = paths["/api/system/plugins/market/publish"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert pub_ref == "#/components/schemas/PluginMarketPublishResponse"
    assert set(schemas["PluginMarketPublishResponse"].get("required") or []) >= {"package_id", "review_status"}

    rev_ref = paths["/api/system/plugins/market/review"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert rev_ref == "#/components/schemas/PluginMarketReviewResponse"

    ins_ref = paths["/api/system/plugins/market/install"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert ins_ref == "#/components/schemas/PluginMarketInstallResponse"

    ins_list_ref = paths["/api/system/plugins/market/installations"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert ins_list_ref == "#/components/schemas/PluginMarketInstallationListResponse"
    assert (
        schemas["PluginMarketInstallationListResponse"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/SystemJsonRecord"
    )

    tg_ref = paths["/api/system/plugins/market/toggle"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert tg_ref == "#/components/schemas/PluginMarketToggleResponse"

    mx_ref = paths["/api/system/plugins/compatibility/matrix"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert mx_ref == "#/components/schemas/PluginCompatibilityMatrixResponse"
    mx = schemas["PluginCompatibilityMatrixResponse"]
    assert set(mx.get("required") or []) == {"gateway_version", "count", "items"}
    items_prop = mx["properties"]["items"]
    assert items_prop.get("items", {}).get("$ref") == "#/components/schemas/PluginCompatibilityMatrixRow"
    row = schemas["PluginCompatibilityMatrixRow"]
    cgv = row["properties"]["compatible_gateway_versions"]
    assert cgv.get("type") == "array"
    assert cgv.get("items", {}).get("type") == "string"

    plug_body = client.get("/api/system/plugins").json()
    assert plug_body["count"] >= 0 and isinstance(plug_body["plugins"], list)

    matrix_body = client.get("/api/system/plugins/compatibility/matrix").json()
    assert "gateway_version" in matrix_body and matrix_body["count"] >= 0
