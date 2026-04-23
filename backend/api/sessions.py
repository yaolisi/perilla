"""
Session / Messages 管理 API（MVP）

注：
- user_id 约定从 Header: X-User-Id 读取；无则 default
- session_id 由 chat/completions 在缺失时自动创建并返回 header X-Session-Id
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, cast

from fastapi import APIRouter, Request

from api.errors import raise_api_error
from config.settings import settings
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.utils.user_context import get_user_id

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _raise_chat_session_not_found(session_id: str) -> None:
    raise_api_error(
        status_code=404,
        code="chat_session_not_found",
        message="session not found",
        details={"session_id": session_id},
    )


def _get_user_id(request: Request) -> str:
    return cast(str, get_user_id(request))


# 使用统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)
_store = HistoryStore(HistoryStoreConfig(db_path=_db_path))


@router.get("")
async def list_sessions(request: Request, limit: int = 50) -> Dict[str, Any]:
    user_id = _get_user_id(request)
    data = _store.list_sessions(user_id=user_id, limit=limit)
    return {"object": "list", "data": data}


@router.get("/{session_id}/messages")
async def list_messages(request: Request, session_id: str, limit: int = 200) -> Dict[str, Any]:
    user_id = _get_user_id(request)
    data = _store.list_messages(user_id=user_id, session_id=session_id, limit=limit)
    if data == [] and not _store.session_exists(user_id=user_id, session_id=session_id):
        _raise_chat_session_not_found(session_id)
    return {"object": "list", "data": data}


@router.patch("/{session_id}")
async def rename_session(request: Request, session_id: str, title: str) -> Dict[str, Any]:
    user_id = _get_user_id(request)
    ok = _store.rename_session(user_id=user_id, session_id=session_id, title=title)
    if not ok:
        _raise_chat_session_not_found(session_id)
    return {"updated": True, "id": session_id, "title": title}


@router.delete("/{session_id}")
async def delete_session(request: Request, session_id: str) -> Dict[str, Any]:
    user_id = _get_user_id(request)
    ok = _store.delete_session(user_id=user_id, session_id=session_id, hard=True)
    if not ok:
        _raise_chat_session_not_found(session_id)
    return {"deleted": True, "id": session_id}

