from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.requests import Request

from api import workflows as workflows_api
from core.data.base import get_db

from tests.helpers import make_fastapi_app_router_only


def _client() -> TestClient:
    app = make_fastapi_app_router_only(workflows_api)

    def _override_get_db(_request: Request):
        class _Db:
            pass

        yield _Db()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[workflows_api.get_current_user] = lambda: "u1"
    return TestClient(app)


def test_openapi_workflows_json_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    impact = paths["/api/v1/workflows/{workflow_id}/impact"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert impact == "#/components/schemas/WorkflowSubworkflowImpactResponse"
    assert (
        schemas["WorkflowSubworkflowImpactResponse"]["properties"]["risk_summary"]["$ref"]
        == "#/components/schemas/WorkflowSubworkflowRiskSummary"
    )

    diff = paths["/api/v1/workflows/{workflow_id}/versions/compare"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert diff == "#/components/schemas/WorkflowVersionsCompareResponse"

    ver = paths["/api/v1/workflows/{workflow_id}/versions/{version_id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert ver == "#/components/schemas/WorkflowVersionDetailResponse"

    failure = paths["/api/v1/workflows/{workflow_id}/executions/{execution_id}/failure-report"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert failure == "#/components/schemas/WorkflowExecutionFailureReportResponse"

    chain = paths["/api/v1/workflows/{workflow_id}/executions/{execution_id}/call-chain"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["$ref"]
    assert chain == "#/components/schemas/WorkflowExecutionCallChainResponse"

    debug = paths["/api/v1/workflows/{workflow_id}/executions/{execution_id}/debug"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert debug == "#/components/schemas/WorkflowExecutionDebugResponse"

    quota_get = paths["/api/v1/workflows/{workflow_id}/quota"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert quota_get == "#/components/schemas/WorkflowGovernanceStatusResponse"

    quota_put = paths["/api/v1/workflows/{workflow_id}/quota"]["put"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert quota_put == "#/components/schemas/WorkflowGovernanceStatusResponse"

    gov_get = paths["/api/v1/workflows/{workflow_id}/governance"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert gov_get == "#/components/schemas/WorkflowGovernanceStatusResponse"

    gov_put = paths["/api/v1/workflows/{workflow_id}/governance"]["put"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert gov_put == "#/components/schemas/WorkflowGovernanceStatusResponse"

    usage = paths["/api/v1/workflows/{workflow_id}/tool-composition/usage"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert usage == "#/components/schemas/ToolCompositionUsageRecordedResponse"


def test_openapi_workflow_list_endpoints_named_item_refs() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas") or {}
    paths = spec.get("paths") or {}

    wl = paths["/api/v1/workflows"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert wl == "#/components/schemas/WorkflowListEnvelope"
    assert (
        schemas["WorkflowListEnvelope"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/WorkflowResponse"
    )

    vl = paths["/api/v1/workflows/{workflow_id}/versions"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert vl == "#/components/schemas/WorkflowVersionListEnvelope"
    assert (
        schemas["WorkflowVersionListEnvelope"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/WorkflowVersionResponse"
    )

    el = paths["/api/v1/workflows/{workflow_id}/executions"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert el == "#/components/schemas/WorkflowExecutionListEnvelope"
    assert (
        schemas["WorkflowExecutionListEnvelope"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/WorkflowExecutionResponse"
    )

    err = paths["/api/v1/workflows/{workflow_id}/executions/{execution_id}/errors"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert err == "#/components/schemas/WorkflowExecutionErrorLogsListEnvelope"
    assert (
        schemas["WorkflowExecutionErrorLogsListEnvelope"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/WorkflowExecutionErrorLogRow"
    )
    row_props = schemas["WorkflowExecutionErrorLogRow"]["properties"]
    for fname in ("error_message", "error_type", "error_stack", "failure_strategy"):
        prop = row_props[fname]
        any_of = prop.get("anyOf") or []
        assert any(item.get("type") == "string" for item in any_of)
        assert any(item.get("type") == "null" for item in any_of)

    au = paths["/api/v1/workflows/{workflow_id}/governance/audits"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert au == "#/components/schemas/WorkflowGovernanceAuditListEnvelope"
    assert (
        schemas["WorkflowGovernanceAuditListEnvelope"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/WorkflowGovernanceAuditEntry"
    )

    rec = paths["/api/v1/workflows/{workflow_id}/tool-composition/templates/recommend"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert rec == "#/components/schemas/ToolCompositionRecommendResponse"
    assert (
        schemas["ToolCompositionRecommendResponse"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/ToolCompositionRecommendItem"
    )


def test_openapi_workflows_json_maps_and_record_lists_use_named_refs() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas") or {}
    jmap = "#/components/schemas/WorkflowJsonMap"
    jrec = "#/components/schemas/WorkflowJsonRecord"

    ex = schemas["WorkflowExecutionResponse"]["properties"]
    assert ex["input_data"]["$ref"] == jmap
    assert ex["output_data"]["anyOf"][0]["$ref"] == jmap
    assert ex["global_context"]["$ref"] == jmap
    assert ex["error_details"]["anyOf"][0]["$ref"] == jmap
    assert ex["replay"]["$ref"] == jmap
    assert ex["node_states"]["items"]["$ref"] == jrec
    assert ex["node_timeline"]["items"]["$ref"] == jrec
    assert ex["agent_summaries"]["items"]["$ref"] == jrec

    st = schemas["WorkflowExecutionStatusResponse"]["properties"]
    assert st["node_timeline"]["items"]["$ref"] == jrec

    fail = schemas["WorkflowExecutionFailureReportResponse"]["properties"]
    assert fail["global_context"]["$ref"] == jmap
    assert fail["global_error_details"]["anyOf"][0]["$ref"] == jmap
    for key in ("recovery_actions", "node_timeline", "node_states", "filtered_error_logs"):
        assert fail[key]["items"]["$ref"] == jrec

    chain = schemas["WorkflowExecutionCallChainItem"]["properties"]
    assert chain["recovery_summaries"]["items"]["$ref"] == jrec
    assert chain["collaboration_summaries"]["items"]["$ref"] == jrec

    dbg = schemas["WorkflowExecutionDebugResponse"]["properties"]
    assert dbg["kernel_snapshot"]["anyOf"][0]["$ref"] == jmap
    assert dbg["recent_events"]["items"]["$ref"] == jrec

    gov = schemas["WorkflowGovernanceStatusResponse"]["properties"]
    assert gov["quota"]["$ref"] == jmap

    appr = schemas["WorkflowApprovalTaskResponse"]["properties"]
    assert appr["payload"]["$ref"] == jmap

    audit = schemas["WorkflowGovernanceAuditEntry"]["properties"]
    assert audit["old_config"]["$ref"] == jmap
    assert audit["new_config"]["$ref"] == jmap

    rec_item = schemas["ToolCompositionRecommendItem"]["properties"]
    assert rec_item["signals"]["$ref"] == jmap


def test_openapi_workflow_approvals_response_any_of_named_refs() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schema = paths["/api/v1/workflows/{workflow_id}/executions/{execution_id}/approvals"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert schema.get("anyOf") is not None
    direct_refs: set[str] = set()
    item_refs: set[str] = set()
    for item in schema["anyOf"]:
        if "$ref" in item:
            direct_refs.add(item["$ref"])
        if item.get("type") == "array":
            ir = (item.get("items") or {}).get("$ref")
            if ir:
                item_refs.add(ir)
    assert "#/components/schemas/WorkflowApprovalListResponse" in direct_refs
    assert "#/components/schemas/WorkflowApprovalTaskResponse" in item_refs


def test_openapi_workflow_execution_stream_declares_lang_query() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    stream_path = spec["paths"]["/api/v1/workflows/{workflow_id}/executions/{execution_id}/stream"]["get"]
    names = {p["name"] for p in stream_path.get("parameters") or []}
    assert "lang" in names
    assert "interval_ms" in names
