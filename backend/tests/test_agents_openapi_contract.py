from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import agents as agents_api
from api.errors import register_error_handlers
from core.security.deps import require_authenticated_platform_admin


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(agents_api.router)
    app.include_router(agents_api.session_router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_openapi_agents_json_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

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

    trace = paths["/api/agent-sessions/{session_id}/trace"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert trace == "#/components/schemas/AgentTraceEventsListEnvelope"

    del_msg = paths["/api/agent-sessions/{session_id}/messages/{message_index}"]["delete"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert del_msg == "#/components/schemas/AgentSession"

    del_sess = paths["/api/agent-sessions/{session_id}"]["delete"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert del_sess == "#/components/schemas/AgentSessionDeletedResponse"
