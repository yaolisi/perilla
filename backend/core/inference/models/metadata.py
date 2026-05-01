"""
推理网关 OpenAPI：命名 JSON 映射类型（避免匿名 object 内联）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class InferenceMetadataJsonMap(BaseModel):
    """推理请求/响应侧透传元数据（路由、会话、缓存命中等）。"""

    model_config = ConfigDict(extra="allow")


class AsrOptionsJsonMap(BaseModel):
    """ASR 运行时可选参数（language、beam_size、vad_filter 等）。"""

    model_config = ConfigDict(extra="allow")


class AsrSegmentJsonMap(BaseModel):
    """ASR 分段结果中的单条片段（字段随实现变化）。"""

    model_config = ConfigDict(extra="allow")


def inference_metadata_as_dict(meta: Any) -> dict[str, Any]:
    """供路由/队列/缓存逻辑使用的 dict 视图。"""
    if meta is None:
        return {}
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, BaseModel):
        return meta.model_dump(mode="python")
    return {}
