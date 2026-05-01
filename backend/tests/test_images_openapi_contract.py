from __future__ import annotations

from fastapi.testclient import TestClient

from api import images as images_api

from tests.helpers import build_minimal_router_test_client


def _client() -> TestClient:
    return build_minimal_router_test_client(images_api)


def test_openapi_images_json_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    gen = paths["/api/v1/images/generate"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    gen_refs = {item["$ref"] for item in gen.get("anyOf", []) if item.get("$ref")}
    if not gen_refs and gen.get("oneOf"):
        gen_refs = {item["$ref"] for item in gen["oneOf"] if item.get("$ref")}
    assert gen_refs == {
        "#/components/schemas/ImageGenerationResponse",
        "#/components/schemas/ImageGenerationJobResponse",
    }

    meta_ref = schemas["ImageGenerationResponse"]["properties"]["metadata"]["$ref"]
    assert meta_ref == "#/components/schemas/ImageGenerationMetadataJsonMap"

    assert (
        paths["/api/v1/images/jobs/{job_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ImageGenerationJobResponse"
    )

    assert (
        paths["/api/v1/images/jobs"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ImageGenerationJobListResponse"
    )
    assert (
        schemas["ImageGenerationJobListResponse"]["properties"]["items"]["items"]["$ref"]
        == "#/components/schemas/ImageGenerationJobResponse"
    )

    assert (
        paths["/api/v1/images/jobs/{job_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ImageGenerationJobDeleteResponse"
    )

    assert (
        paths["/api/v1/images/jobs/{job_id}/cancel"]["post"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/ImageGenerationJobResponse"
    )

    assert (
        paths["/api/v1/images/warmup/latest"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ImageGenerationWarmupResponse"
    )

    assert (
        paths["/api/v1/images/warmup"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ImageGenerationWarmupCompletedResponse"
    )
