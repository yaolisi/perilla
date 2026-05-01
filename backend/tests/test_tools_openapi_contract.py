from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import tools as tools_api
from api.errors import register_error_handlers


def _build_client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(tools_api.router)
    return TestClient(app)


def test_openapi_tools_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    d_ref = paths["/api/tools/web-search/diagnostic"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert d_ref == "#/components/schemas/WebSearchDiagnosticResponse"

    lst_ref = paths["/api/tools"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert lst_ref == "#/components/schemas/ToolListResponse"
    tl = schemas["ToolListResponse"]
    assert tl["properties"]["object"]["const"] == "list"
    data_prop = tl["properties"]["data"]
    assert data_prop.get("items", {}).get("$ref") == "#/components/schemas/ToolDescriptorResponse"

    pr_ref = paths["/api/tools/web-search/probe"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert pr_ref == "#/components/schemas/WebSearchProbeResponse"
    assert (
        schemas["WebSearchProbeResponse"]["properties"]["diagnostic"]["$ref"]
        == "#/components/schemas/WebSearchDiagnosticResponse"
    )
    res_prop = schemas["WebSearchProbeResponse"]["properties"]["results"]
    res_item_refs = [
        opt.get("items", {}).get("$ref")
        for opt in (res_prop.get("anyOf") or [])
        if isinstance(opt, dict) and opt.get("type") == "array"
    ]
    if res_prop.get("items", {}).get("$ref"):
        res_item_refs.append(res_prop["items"]["$ref"])
    assert "#/components/schemas/WebSearchResultItem" in res_item_refs

    gt_ref = paths["/api/tools/{name}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert gt_ref == "#/components/schemas/ToolDescriptorResponse"

    jmap = "#/components/schemas/ToolJsonMap"
    td = schemas["ToolDescriptorResponse"]["properties"]
    assert td["input_schema"]["$ref"] == jmap
    assert td["output_schema"]["$ref"] == jmap
    assert td["ui"]["anyOf"][0]["$ref"] == jmap

    diag_body = client.get("/api/tools/web-search/diagnostic").json()
    assert "python" in diag_body and "duckduckgo_search" in diag_body

    list_body = client.get("/api/tools").json()
    assert list_body["object"] == "list" and isinstance(list_body["data"], list)
