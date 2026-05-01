"""
V2.8 Inference Gateway Layer - Embedding Response Model
"""

from typing import List

from pydantic import BaseModel, Field

from core.inference.models.metadata import InferenceMetadataJsonMap


class EmbeddingResponse(BaseModel):
    """
    Unified embedding response.

    Attributes:
        embeddings: List of embedding vectors (one per input item)
        provider: Provider name
        model: Actual model id used
        model_alias: Original alias requested
        metadata: Additional response metadata
    """

    embeddings: List[List[float]] = Field(default_factory=list, description="Embedding vectors")
    provider: str = Field(default="", description="Provider name")
    model: str = Field(default="", description="Actual model used")
    model_alias: str = Field(default="", description="Original alias requested")
    metadata: InferenceMetadataJsonMap = Field(
        default_factory=InferenceMetadataJsonMap,
        description="Additional metadata",
    )

    @property
    def success(self) -> bool:
        return bool(self.embeddings)

