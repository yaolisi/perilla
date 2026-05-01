from __future__ import annotations

from fastapi.testclient import TestClient

from api import collaboration as collaboration_api
from api import rag_trace as rag_trace_api
from api import skill_discovery as skill_discovery_api
from core.security.deps import require_authenticated_platform_admin
from middleware import user_context as user_context_mw

from tests.helpers import make_fastapi_app_router_only


def test_openapi_rag_trace_internal_named_schemas() -> None:
    app = make_fastapi_app_router_only(rag_trace_api)
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}

    chunks_body = paths["/api/rag/internal/trace/{trace_id}/chunks"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert chunks_body["items"]["$ref"] == "#/components/schemas/RAGTraceChunk"

    st = paths["/api/rag/internal/trace/start"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert st == "#/components/schemas/RagTraceStartResponse"

    ch = paths["/api/rag/internal/trace/{trace_id}/chunks"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert ch == "#/components/schemas/RagTraceAckResponse"

    fn = paths["/api/rag/internal/trace/{trace_id}/finalize"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert fn == "#/components/schemas/RagTraceAckResponse"

    by_msg = paths["/api/rag/trace/by-message/{message_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert by_msg == "#/components/schemas/RAGTraceResponse"

    by_id = paths["/api/rag/trace/{trace_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert by_id == "#/components/schemas/RAGTraceResponse"


def test_openapi_collaboration_message_upsert_named_schema() -> None:
    app = make_fastapi_app_router_only(collaboration_api)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    ref = paths["/api/collaboration/messages"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/CollaborationMessageUpsertResponse"
    assert (
        schemas["CollaborationMessageUpsertResponse"]["properties"]["message"]["$ref"]
        == "#/components/schemas/CollaborationMessageRecord"
    )
    jmap = "#/components/schemas/CollaborationJsonMap"
    assert schemas["CollaborationMessageRecord"]["properties"]["content"]["$ref"] == jmap
    meta_any = schemas["CollaborationMessageRecord"]["properties"]["meta"]["anyOf"]
    assert meta_any[0]["$ref"] == jmap
    upsert_body = paths["/api/collaboration/messages"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert upsert_body == "#/components/schemas/CollaborationMessageUpsertRequest"
    upsert_props = schemas["CollaborationMessageUpsertRequest"]["properties"]
    assert upsert_props["content"]["$ref"] == jmap
    assert upsert_props["meta"]["anyOf"][0]["$ref"] == jmap
    invoked_any = schemas["CollaborationStateBlock"]["properties"]["invoked_from"]["anyOf"]
    assert invoked_any[0]["$ref"] == jmap

    msg_list_ref = paths["/api/collaboration/correlation/{correlation_id}/messages"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert msg_list_ref == "#/components/schemas/CollaborationMessageListResponse"
    assert (
        schemas["CollaborationMessageListResponse"]["properties"]["messages"]["items"]["$ref"]
        == "#/components/schemas/CollaborationMessageRecord"
    )

    assert (
        paths["/api/collaboration/correlation/{correlation_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/CorrelationSummaryResponse"
    )
    assert (
        schemas["CorrelationSummaryResponse"]["properties"]["sessions"]["items"]["$ref"]
        == "#/components/schemas/SessionCollaborationItem"
    )
    assert (
        schemas["SessionCollaborationItem"]["properties"]["collaboration"]["$ref"]
        == "#/components/schemas/CollaborationStateBlock"
    )
    msgs_prop = schemas["CollaborationStateBlock"]["properties"]["messages"]
    msg_item_refs = [
        opt.get("items", {}).get("$ref")
        for opt in (msgs_prop.get("anyOf") or [])
        if isinstance(opt, dict) and opt.get("type") == "array"
    ]
    if msgs_prop.get("items", {}).get("$ref"):
        msg_item_refs.append(msgs_prop["items"]["$ref"])
    assert "#/components/schemas/CollaborationMessageRecord" in msg_item_refs


def test_openapi_skill_discovery_named_schemas() -> None:
    app = make_fastapi_app_router_only(skill_discovery_api)
    app.dependency_overrides[user_context_mw.get_current_user] = lambda: "contract-test-user"
    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    sch = paths["/api/skill-discovery/search"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert sch.get("anyOf") is not None
    refs = {x["$ref"] for x in sch["anyOf"]}
    assert refs == {
        "#/components/schemas/SkillSearchBasicResponse",
        "#/components/schemas/SkillSearchScoredResponse",
    }
    assert (
        schemas["SkillSearchBasicResponse"]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/SkillDefinitionDiscoveryRecord"
    )
    assert (
        schemas["SkillSearchScoredResponse"]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/SkillSearchScoredRow"
    )
    assert (
        schemas["SkillSearchScoredRow"]["properties"]["skill"]["$ref"]
        == "#/components/schemas/SkillDefinitionDiscoveryRecord"
    )

    rec = paths["/api/skill-discovery/recommend"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert rec == "#/components/schemas/SkillRecommendationResponse"
    assert (
        schemas["SkillRecommendationResponse"]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/SkillDefinitionDiscoveryRecord"
    )
    jmap = "#/components/schemas/SkillDiscoveryJsonMap"
    sddr = schemas["SkillDefinitionDiscoveryRecord"]["properties"]
    assert sddr["definition"]["$ref"] == jmap
    assert sddr["input_schema"]["$ref"] == jmap
    assert sddr["output_schema"]["$ref"] == jmap
