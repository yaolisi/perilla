from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import knowledge as knowledge_api
from api.errors import register_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(knowledge_api.router)
    return TestClient(app)


def _assert_optional_string_field(schemas: dict, model: str, field: str) -> None:
    prop = schemas[model]["properties"][field]
    any_of = prop.get("anyOf") or []
    if any_of:
        assert any(item.get("type") == "string" for item in any_of)
        assert any(item.get("type") == "null" for item in any_of)
    else:
        assert prop.get("type") == "string"


def test_openapi_knowledge_named_schemas() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    assert (
        paths["/api/knowledge-bases"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseCreatedResponse"
    )
    assert (
        paths["/api/knowledge-bases"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseListEnvelope"
    )
    assert schemas["KnowledgeBaseListEnvelope"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/KnowledgeBaseRecordResponse"

    kb_one = paths["/api/knowledge-bases/{kb_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert kb_one == "#/components/schemas/KnowledgeBaseRecordResponse"

    assert (
        paths["/api/knowledge-bases/{kb_id}"]["patch"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseRecordResponse"
    )
    assert (
        paths["/api/knowledge-bases/{kb_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseDeleteResponse"
    )

    assert (
        paths["/api/models/embedding"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/EmbeddingModelListEnvelope"
    )
    assert (
        schemas["EmbeddingModelListEnvelope"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/EmbeddingModelInfo"
    )

    assert (
        paths["/api/knowledge-bases/{kb_id}/stats"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeBaseStatsResponse"
    )

    assert (
        paths["/api/knowledge-bases/{kb_id}/documents"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeDocumentListEnvelope"
    )
    assert (
        schemas["KnowledgeDocumentListEnvelope"]["properties"]["data"]["items"]["$ref"]
        == "#/components/schemas/KnowledgeDocumentRecordResponse"
    )

    doc_one = paths["/api/knowledge-bases/{kb_id}/documents/{doc_id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert doc_one == "#/components/schemas/KnowledgeDocumentRecordResponse"

    assert (
        paths["/api/knowledge-bases/{kb_id}/documents"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/DocumentUploadResponse"
    )
    assert (
        paths["/api/knowledge-bases/{kb_id}/documents/{doc_id}"]["delete"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/DocumentDeleteResponse"
    )
    assert (
        paths["/api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/DocumentReindexResponse"
    )

    assert (
        paths["/api/knowledge-bases/{kb_id}/chunks"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeChunkListEnvelope"
    )
    assert schemas["KnowledgeChunkListEnvelope"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/KnowledgeChunkItem"

    assert (
        paths["/api/knowledge-bases/{kb_id}/search"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeSearchResponse"
    )
    assert schemas["KnowledgeSearchResponse"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/KnowledgeSearchHit"

    jmap = "#/components/schemas/KnowledgeJsonMap"
    sint = "#/components/schemas/KnowledgeStringIntMap"
    assert schemas["KnowledgeBaseRecordResponse"]["properties"]["disk_size"]["anyOf"][0]["$ref"] == jmap
    assert schemas["KnowledgeBaseCreatedResponse"]["properties"]["chunk_size_overrides"]["$ref"] == sint
    assert schemas["KnowledgeBaseStatsResponse"]["properties"]["disk_size"]["$ref"] == jmap
    assert schemas["KnowledgeBaseStatsResponse"]["properties"]["document_status_breakdown"]["$ref"] == sint
    assert schemas["KnowledgeChunkItem"]["properties"]["metadata"]["anyOf"][0]["$ref"] == jmap
    assert (
        paths["/api/knowledge-bases"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/CreateKnowledgeBaseRequest"
    )
    assert schemas["CreateKnowledgeBaseRequest"]["properties"]["chunk_size_overrides"]["$ref"] == sint

    _assert_optional_string_field(schemas, "KnowledgeBaseRecordResponse", "created_at")
    _assert_optional_string_field(schemas, "KnowledgeDocumentRecordResponse", "created_at")
    _assert_optional_string_field(schemas, "KnowledgeDocumentRecordResponse", "updated_at")
    _assert_optional_string_field(schemas, "KbVersionRecordResponse", "created_at")
    _assert_optional_string_field(schemas, "KnowledgeGraphRelationRow", "created_at")

    assert (
        paths["/api/knowledge-bases/{kb_id}/versions"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KbVersionCreatedResponse"
    )
    assert (
        paths["/api/knowledge-bases/{kb_id}/versions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KbVersionListEnvelope"
    )
    assert schemas["KbVersionListEnvelope"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/KbVersionRecordResponse"

    assert (
        paths["/api/knowledge-bases/{kb_id}/graph/search"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/KnowledgeGraphSearchEnvelope"
    )
    assert (
        schemas["KnowledgeGraphSearchEnvelope"]["properties"]["data"]["items"]["$ref"] == "#/components/schemas/KnowledgeGraphRelationRow"
    )
