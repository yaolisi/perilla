from __future__ import annotations

from fastapi.testclient import TestClient

from api import agents as agents_api
from core.security.deps import require_authenticated_platform_admin

from tests.helpers import make_fastapi_app_router_only


def _client() -> TestClient:
    app = make_fastapi_app_router_only(agents_api.router, agents_api.session_router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_openapi_agents_json_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    env_ref = "#/components/schemas/APIErrorHttpEnvelope"
    post_responses = paths["/api/agents"]["post"]["responses"]
    assert post_responses["400"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert post_responses["503"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    put_responses = paths["/api/agents/{agent_id}"]["put"]["responses"]
    assert put_responses["400"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert put_responses["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert put_responses["503"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert schemas["APIErrorHttpEnvelope"]["properties"]["error"]["$ref"] == "#/components/schemas/APIError"

    nl_resp = paths["/api/agents/generate-from-nl"]["post"]["responses"]
    assert nl_resp["400"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert nl_resp["503"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    assert (
        paths["/api/agents/{agent_id}"]["get"]["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
        == env_ref
    )
    assert (
        paths["/api/agents/{agent_id}"]["delete"]["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
        == env_ref
    )

    run_post_resp = paths["/api/agents/{agent_id}/run"]["post"]["responses"]
    assert run_post_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    run_files_post_resp = paths["/api/agents/{agent_id}/run/with-files"]["post"]["responses"]
    assert run_files_post_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert run_files_post_resp["413"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    list_agents = paths["/api/agents"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert list_agents == "#/components/schemas/AgentsListEnvelope"
    assert (
        schemas["AgentsListEnvelope"]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/AgentWithSkillsMetaResponse"
    )
    meta_prop = schemas["AgentWithSkillsMetaResponse"]["properties"]["enabled_skills_meta"]
    meta_refs = [
        opt.get("items", {}).get("$ref")
        for opt in (meta_prop.get("anyOf") or [])
        if isinstance(opt, dict) and opt.get("type") == "array"
    ]
    if meta_prop.get("items", {}).get("$ref"):
        meta_refs.append(meta_prop["items"]["$ref"])
    assert "#/components/schemas/EnabledSkillMetaItem" in meta_refs

    assert (
        schemas["AgentWithSkillsMetaResponse"]["properties"]["model_params"]["$ref"]
        == "#/components/schemas/AgentModelParamsJsonMap"
    )

    create_body = paths["/api/agents"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert create_body == "#/components/schemas/CreateAgentRequest"
    jmap = "#/components/schemas/AgentModelParamsJsonMap"
    assert schemas["CreateAgentRequest"]["properties"]["model_params"]["anyOf"][0]["$ref"] == jmap

    run_body = paths["/api/agents/{agent_id}/run"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert run_body == "#/components/schemas/RunAgentRequest"
    assert schemas["RunAgentRequest"]["properties"]["invoked_from"]["anyOf"][0]["$ref"] == jmap

    create_agent = paths["/api/agents"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert create_agent == "#/components/schemas/AgentWithSkillsMetaResponse"

    nl = paths["/api/agents/generate-from-nl"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert nl == "#/components/schemas/GenerateAgentFromNlResult"

    get_one = paths["/api/agents/{agent_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert get_one == "#/components/schemas/AgentWithSkillsMetaResponse"

    put_one = paths["/api/agents/{agent_id}"]["put"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert put_one == "#/components/schemas/AgentWithSkillsMetaResponse"

    del_one = paths["/api/agents/{agent_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert del_one == "#/components/schemas/AgentDeleteOkResponse"

    run = paths["/api/agents/{agent_id}/run"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert run == "#/components/schemas/AgentSession"
    assert schemas["AgentSession"]["properties"]["state"]["$ref"] == "#/components/schemas/AgentSessionStateJsonMap"

    run_files = paths["/api/agents/{agent_id}/run/with-files"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert run_files == "#/components/schemas/AgentSession"


def test_openapi_agent_sessions_json_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}

    env_ref = "#/components/schemas/APIErrorHttpEnvelope"

    one_resp = paths["/api/agent-sessions/{session_id}"]["get"]["responses"]
    assert one_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    stream_op = paths["/api/agent-sessions/{session_id}/stream"]["get"]
    stream_resp = stream_op["responses"]
    assert stream_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    stream_param_names = {p["name"] for p in stream_op.get("parameters") or []}
    assert "lang" in stream_param_names

    files_resp = paths["/api/agent-sessions/{session_id}/files/{filename}"]["get"]["responses"]
    assert files_resp["400"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert files_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    patch_resp = paths["/api/agent-sessions/{session_id}"]["patch"]["responses"]
    assert patch_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    assert patch_resp["500"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    del_msg_resp = paths["/api/agent-sessions/{session_id}/messages/{message_index}"]["delete"]["responses"]
    assert del_msg_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    del_sess_resp = paths["/api/agent-sessions/{session_id}"]["delete"]["responses"]
    assert del_sess_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref

    lst = paths["/api/agent-sessions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert lst == "#/components/schemas/AgentSessionsListEnvelope"

    one = paths["/api/agent-sessions/{session_id}"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert one == "#/components/schemas/AgentSession"

    patch = paths["/api/agent-sessions/{session_id}"]["patch"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert patch == "#/components/schemas/AgentSession"

    trace_op = paths["/api/agent-sessions/{session_id}/trace"]["get"]
    trace_resp = trace_op["responses"]
    assert trace_resp["404"]["content"]["application/json"]["schema"]["$ref"] == env_ref
    trace = trace_resp["200"]["content"]["application/json"]["schema"]["$ref"]
    assert trace == "#/components/schemas/AgentTraceEventsListEnvelope"

    del_msg = paths["/api/agent-sessions/{session_id}/messages/{message_index}"]["delete"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert del_msg == "#/components/schemas/AgentSession"

    del_sess = paths["/api/agent-sessions/{session_id}"]["delete"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert del_sess == "#/components/schemas/AgentSessionDeletedResponse"
