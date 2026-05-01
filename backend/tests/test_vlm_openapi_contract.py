from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import vlm as vlm_api
from api.errors import register_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(vlm_api.router)
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


def test_openapi_vlm_generate_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    assert (
        paths["/v1/vlm/generate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/VLMGenerateResponse"
    )

    props = schemas["VLMGenerateResponse"]["properties"]
    assert "#/components/schemas/ChatCompletionUsage" in _schema_refs(props["usage"])
    assert "#/components/schemas/VlmGenerateRoutingMetadata" in _schema_refs(props["metadata"])
