"""
Memory 管理 API（MVP）

满足：
- list（按 user_id）
- delete（按 user_id + id）
- clear（按 user_id）

user_id 约定从 Header: X-User-Id 读取；无则 default
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from api.errors import raise_api_error
from config.settings import settings
from core.memory.memory_item import MemoryItem
from core.memory.memory_store import MemoryStore, MemoryStoreConfig
from core.utils.tenant_request import get_effective_tenant_id

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[MemoryItem]


class MemoryDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: Literal[True] = True
    id: str


class MemoryClearResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cleared: Literal[True] = True
    deleted_count: int


def _get_user_id(request: Request) -> str:
    uid = (request.headers.get("X-User-Id") or "").strip()
    return uid or "default"


# 使用统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)

_store = MemoryStore(
    MemoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
        default_confidence=settings.memory_default_confidence,
        merge_enabled=bool(settings.memory_merge_enabled),
        merge_similarity_threshold=settings.memory_merge_similarity_threshold,
        conflict_enabled=bool(settings.memory_conflict_enabled),
        conflict_similarity_threshold=settings.memory_conflict_similarity_threshold,
        key_schema_enforced=bool(settings.memory_key_schema_enforced),
        key_schema_allow_unlisted=bool(settings.memory_key_schema_allow_unlisted),
    )
)


@router.get("")
async def list_memory(
    request: Request, limit: int = 50, include_deprecated: bool = False
) -> MemoryListResponse:
    """列出当前用户的记忆（最近优先）"""
    user_id = _get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    items = _store.list(
        user_id=user_id,
        limit=limit,
        include_deprecated=include_deprecated,
        tenant_id=tenant_id,
    )
    return MemoryListResponse(data=items)


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, request: Request) -> MemoryDeleteResponse:
    """删除一条记忆"""
    user_id = _get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    ok = _store.delete(user_id=user_id, memory_id=memory_id, tenant_id=tenant_id)
    if not ok:
        raise_api_error(
            status_code=404,
            code="memory_not_found",
            message="memory not found",
            details={"memory_id": memory_id},
        )
    return MemoryDeleteResponse(id=memory_id)


@router.post("/clear")
async def clear_memory(request: Request) -> MemoryClearResponse:
    """清空当前用户的所有记忆"""
    user_id = _get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    n = _store.clear(user_id=user_id, tenant_id=tenant_id)
    return MemoryClearResponse(deleted_count=n)

