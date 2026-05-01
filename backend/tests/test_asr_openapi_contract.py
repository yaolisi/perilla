from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import asr as asr_api
from api.errors import register_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(asr_api.router)
    return TestClient(app)


def test_openapi_asr_transcribe_response_named_segment_schema() -> None:
    client = _client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    ref = paths["/api/asr/transcribe"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/ASRTranscribeResponse"

    seg_ref = schemas["ASRTranscribeResponse"]["properties"]["segments"]["items"]["$ref"]
    assert seg_ref == "#/components/schemas/AsrSegmentJsonMap"
