from __future__ import annotations

from fastapi.testclient import TestClient

from api import memory as memory_api
from api import sessions as sessions_api

from tests.helpers import build_minimal_router_test_client


def _memory_client() -> TestClient:
    return build_minimal_router_test_client(memory_api)


def _sessions_client() -> TestClient:
    return build_minimal_router_test_client(sessions_api)


def test_openapi_memory_named_schemas() -> None:
    client = _memory_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    lst = paths["/api/memory"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert lst == "#/components/schemas/MemoryListResponse"
    ml = schemas["MemoryListResponse"]
    assert ml["properties"]["object"]["const"] == "list"
    assert ml["properties"]["data"]["items"]["$ref"] == "#/components/schemas/MemoryItem"
    meta_any = schemas["MemoryItem"]["properties"]["meta"].get("anyOf") or []
    meta_refs = {item["$ref"] for item in meta_any if item.get("$ref")}
    assert "#/components/schemas/MemoryItemMetaJsonMap" in meta_refs

    del_ref = paths["/api/memory/{memory_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert del_ref == "#/components/schemas/MemoryDeleteResponse"

    clr_ref = paths["/api/memory/clear"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert clr_ref == "#/components/schemas/MemoryClearResponse"

    body = client.get("/api/memory").json()
    assert body["object"] == "list" and isinstance(body["data"], list)


def test_openapi_sessions_named_schemas() -> None:
    client = _sessions_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    ls_ref = paths["/api/sessions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ls_ref == "#/components/schemas/ChatSessionListResponse"
    assert schemas["ChatSessionListResponse"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/ChatSessionRecord"

    msg_ref = paths["/api/sessions/{session_id}/messages"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert msg_ref == "#/components/schemas/ChatMessageListResponse"
    assert schemas["ChatMessageListResponse"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/ChatMessageRecord"
    content_prop = schemas["ChatMessageRecord"]["properties"]["content"]
    content_any_of = content_prop.get("anyOf") or []
    array_branch = next((x for x in content_any_of if x.get("type") == "array"), None)
    assert array_branch is not None
    assert (
        array_branch.get("items", {}).get("$ref") == "#/components/schemas/ChatCompletionMessageContentItem"
    )
    meta_any = schemas["ChatMessageRecord"]["properties"]["meta"]["anyOf"]
    assert meta_any[0]["$ref"] == "#/components/schemas/ChatMessageMetaMap"

    ren_ref = paths["/api/sessions/{session_id}"]["patch"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ren_ref == "#/components/schemas/ChatSessionRenameResponse"

    del_ref = paths["/api/sessions/{session_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert del_ref == "#/components/schemas/ChatSessionDeleteResponse"
