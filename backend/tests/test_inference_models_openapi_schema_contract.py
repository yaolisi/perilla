"""推理网关 Pydantic 模型：metadata/options/segments 等使用命名 $defs，避免匿名 object。"""

from __future__ import annotations

from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse


def _ref_to_named(schema: dict, prop: str) -> str:
    return schema["properties"][prop]["$ref"]


def test_inference_and_embedding_metadata_named_defs() -> None:
    for model in (InferenceRequest, InferenceResponse, EmbeddingRequest, EmbeddingResponse):
        sch = model.model_json_schema()
        defs = sch.get("$defs") or {}
        assert "InferenceMetadataJsonMap" in defs, model.__name__
        assert _ref_to_named(sch, "metadata") == "#/$defs/InferenceMetadataJsonMap"


def test_asr_request_options_and_metadata_defs() -> None:
    sch = ASRRequest.model_json_schema()
    defs = sch.get("$defs") or {}
    assert "AsrOptionsJsonMap" in defs
    assert "InferenceMetadataJsonMap" in defs
    assert _ref_to_named(sch, "options") == "#/$defs/AsrOptionsJsonMap"
    assert _ref_to_named(sch, "metadata") == "#/$defs/InferenceMetadataJsonMap"


def test_asr_response_segments_and_metadata_defs() -> None:
    sch = ASRResponse.model_json_schema()
    defs = sch.get("$defs") or {}
    assert "AsrSegmentJsonMap" in defs
    assert "InferenceMetadataJsonMap" in defs
    items_ref = sch["properties"]["segments"]["items"]["$ref"]
    assert items_ref == "#/$defs/AsrSegmentJsonMap"
    assert _ref_to_named(sch, "metadata") == "#/$defs/InferenceMetadataJsonMap"
