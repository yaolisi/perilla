"""
V2.8 Inference Gateway Layer - ASR Response Model
"""

from typing import List

from pydantic import BaseModel, Field

from core.inference.models.metadata import AsrSegmentJsonMap, InferenceMetadataJsonMap


class ASRResponse(BaseModel):
    """
    Unified ASR response.

    Attributes:
        text: Full transcription text
        language: Detected language
        segments: Optional timestamp segments
        provider: Provider name
        model: Actual model id used
        model_alias: Original alias requested
        metadata: Additional response metadata
    """

    text: str = Field(default="", description="Transcription text")
    language: str = Field(default="unknown", description="Detected language")
    segments: List[AsrSegmentJsonMap] = Field(default_factory=list, description="Timestamp segments")
    provider: str = Field(default="", description="Provider name")
    model: str = Field(default="", description="Actual model used")
    model_alias: str = Field(default="", description="Original alias requested")
    metadata: InferenceMetadataJsonMap = Field(
        default_factory=InferenceMetadataJsonMap,
        description="Additional metadata",
    )

    @property
    def success(self) -> bool:
        return bool(self.text.strip())

