from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import mcp as mcp_api
from api.errors import register_error_handlers
from core.security.deps import require_authenticated_platform_admin


def _build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(mcp_api.router)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def _schema_refs(prop: dict) -> set[str]:
    out: set[str] = set()
    ref = prop.get("$ref")
    if ref:
        out.add(ref)
    for entry in prop.get("anyOf") or prop.get("oneOf") or []:
        if isinstance(entry, dict) and entry.get("$ref"):
            out.add(entry["$ref"])
    return out


def test_openapi_mcp_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    env_named = "#/components/schemas/McpEnvMap"
    assert schemas["McpServerRecord"]["properties"]["env"]["$ref"] == env_named
    probe_req = paths["/api/mcp/probe"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert probe_req == "#/components/schemas/ProbeBody"
    assert env_named in _schema_refs(schemas["ProbeBody"]["properties"]["env"])
    assert env_named in _schema_refs(schemas["CreateMcpServerBody"]["properties"]["env"])
    assert env_named in _schema_refs(schemas["UpdateMcpServerBody"]["properties"]["env"])
    assert schemas["McpEnvMap"]["additionalProperties"]["type"] == "string"

    probe_ref = paths["/api/mcp/probe"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert probe_ref == "#/components/schemas/McpProbeResponse"
    assert set(schemas["McpProbeResponse"].get("required") or []) >= {"tools"}
    assert schemas["McpProbeResponse"]["properties"]["tools"]["items"]["$ref"] == "#/components/schemas/McpToolDescriptor"
    assert (
        schemas["McpToolDescriptor"]["properties"]["inputSchema"]["anyOf"][0]["$ref"]
        == "#/components/schemas/McpJsonMap"
    )

    lst_ref = paths["/api/mcp/servers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert lst_ref == "#/components/schemas/McpServerListResponse"
    assert schemas["McpServerListResponse"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/McpServerRecord"

    cre_ref = paths["/api/mcp/servers"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cre_ref == "#/components/schemas/McpServerRecord"

    srv = paths["/api/mcp/servers/{server_id}"]
    assert srv["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/McpServerRecord"
    assert srv["put"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/McpServerRecord"
    assert srv["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/McpServerDeleteResponse"

    tools_ref = paths["/api/mcp/servers/{server_id}/tools"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert tools_ref == "#/components/schemas/McpServerToolsResponse"
    assert schemas["McpServerToolsResponse"]["properties"]["tools"]["items"]["$ref"] == "#/components/schemas/McpToolDescriptor"

    prev_ref = paths["/api/mcp/servers/{server_id}/skill-previews"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert prev_ref == "#/components/schemas/McpSkillPreviewsResponse"
    assert (
        schemas["McpSkillPreviewsResponse"]["properties"]["skill_previews"]["items"]["$ref"]
        == "#/components/schemas/SkillDefinitionDiscoveryRecord"
    )

    imp_ref = paths["/api/mcp/servers/{server_id}/import-tools"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert imp_ref == "#/components/schemas/McpImportToolsResponse"
    imp = schemas["McpImportToolsResponse"]
    assert set(imp.get("required") or []) == {"imported", "skipped_existing", "errors"}
    assert imp["properties"]["errors"]["items"]["$ref"] == "#/components/schemas/McpImportErrorRow"
