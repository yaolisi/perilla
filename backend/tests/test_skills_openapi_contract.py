from __future__ import annotations

from fastapi.testclient import TestClient

from api import skills as skills_api
from core.security.deps import require_authenticated_platform_admin

from tests.helpers import make_fastapi_app_router_only


def _build_client() -> TestClient:
    app = make_fastapi_app_router_only(skills_api)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_openapi_skills_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    cr = paths["/api/skills"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cr == "#/components/schemas/SkillV1ApiRecord"

    ls = paths["/api/skills"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ls == "#/components/schemas/SkillListResponse"
    sl = schemas["SkillListResponse"]
    assert sl["properties"]["object"]["const"] == "list"
    assert sl["properties"]["data"]["items"]["$ref"] == "#/components/schemas/SkillV1ApiRecord"

    g_ref = paths["/api/skills/{skill_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert g_ref == "#/components/schemas/SkillV1ApiRecord"

    u_ref = paths["/api/skills/{skill_id}"]["put"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert u_ref == "#/components/schemas/SkillV1ApiRecord"

    d_ref = paths["/api/skills/{skill_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert d_ref == "#/components/schemas/SkillDeleteApiResponse"
    assert schemas["SkillDeleteApiResponse"]["properties"]["status"]["const"] == "ok"

    ex = paths["/api/skills/{skill_id}/execute"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ex.get("anyOf") is not None
    refs = {item["$ref"] for item in ex["anyOf"]}
    assert refs == {
        "#/components/schemas/SkillExecuteSuccessResponse",
        "#/components/schemas/SkillExecuteErrorResponse",
    }

    jmap = "#/components/schemas/SkillV1JsonMap"
    assert schemas["SkillExecuteSuccessResponse"]["properties"]["output"]["$ref"] == jmap
    rec_props = schemas["SkillV1ApiRecord"]["properties"]
    assert rec_props["definition"]["$ref"] == jmap
    assert rec_props["input_schema"]["$ref"] == jmap

    cr_body = paths["/api/skills"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert cr_body == "#/components/schemas/CreateSkillBody"
    cr_props = schemas["CreateSkillBody"]["properties"]
    assert cr_props["definition"]["anyOf"][0]["$ref"] == jmap
    assert cr_props["input_schema"]["anyOf"][0]["$ref"] == jmap

    up_body = paths["/api/skills/{skill_id}"]["put"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert up_body == "#/components/schemas/UpdateSkillBody"
    up_props = schemas["UpdateSkillBody"]["properties"]
    assert up_props["definition"]["anyOf"][0]["$ref"] == jmap
    assert up_props["input_schema"]["anyOf"][0]["$ref"] == jmap

    ex_body = paths["/api/skills/{skill_id}/execute"]["post"]["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert ex_body == "#/components/schemas/ExecuteSkillBody"
    assert schemas["ExecuteSkillBody"]["properties"]["inputs"]["$ref"] == jmap

    lst = client.get("/api/skills")
    assert lst.status_code == 200
    body = lst.json()
    assert body["object"] == "list" and isinstance(body["data"], list)
