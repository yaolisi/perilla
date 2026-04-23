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
from typing import Any, Dict

from fastapi import APIRouter, Request

from api.errors import raise_api_error
from config.settings import settings
from core.memory.memory_store import MemoryStore, MemoryStoreConfig

router = APIRouter(prefix="/api/memory", tags=["memory"])


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
) -> Dict[str, Any]:
    """列出当前用户的记忆（最近优先）"""
    user_id = _get_user_id(request)
    items = _store.list(user_id=user_id, limit=limit, include_deprecated=include_deprecated)
    return {"object": "list", "data": [i.model_dump() for i in items]}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, request: Request) -> Dict[str, Any]:
    """删除一条记忆"""
    user_id = _get_user_id(request)
    ok = _store.delete(user_id=user_id, memory_id=memory_id)
    if not ok:
        raise_api_error(
            status_code=404,
            code="memory_not_found",
            message="memory not found",
            details={"memory_id": memory_id},
        )
    return {"deleted": True, "id": memory_id}


@router.post("/clear")
async def clear_memory(request: Request) -> Dict[str, Any]:
    """清空当前用户的所有记忆"""
    user_id = _get_user_id(request)
    n = _store.clear(user_id=user_id)
    return {"cleared": True, "deleted_count": n}

