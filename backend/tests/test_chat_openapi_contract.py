from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import chat as chat_api
from api.errors import register_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat_api.router)
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


def test_openapi_chat_completion_named_metadata_schema() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    post = paths["/v1/chat/completions"]["post"]
    assert post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/ChatCompletionResponse"

    meta_named = "#/components/schemas/ChatCompletionMetadataJsonMap"
    req_meta = schemas["ChatCompletionRequest"]["properties"]["metadata"]
    assert meta_named in _schema_refs(req_meta)

    res_meta = schemas["ChatCompletionResponse"]["properties"]["metadata"]
    assert meta_named in _schema_refs(res_meta)

    choices_prop = schemas["ChatCompletionResponse"]["properties"]["choices"]
    assert choices_prop["type"] == "array"
    assert choices_prop["items"]["$ref"] == "#/components/schemas/ChatCompletionChoice"

    msg_prop = schemas["ChatCompletionChoice"]["properties"]["message"]
    assert msg_prop["$ref"] == "#/components/schemas/ChatCompletionChoiceMessage"

    content_prop = schemas["ChatCompletionChoiceMessage"]["properties"]["content"]
    any_of = content_prop.get("anyOf") or []
    array_branch = next((x for x in any_of if x.get("type") == "array"), None)
    assert array_branch is not None
    assert (
        array_branch.get("items", {}).get("$ref") == "#/components/schemas/ChatCompletionMessageContentItem"
    )

    usage_prop = schemas["ChatCompletionResponse"]["properties"]["usage"]
    assert "#/components/schemas/ChatCompletionUsage" in _schema_refs(usage_prop)

    img_part = schemas["MessageContentItem"]["properties"]["image_url"]
    assert "#/components/schemas/MessageImageUrlPayload" in _schema_refs(img_part)
