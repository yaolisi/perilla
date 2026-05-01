"""
Session / Messages 管理 API（MVP）

注：
- user_id 约定从 Header: X-User-Id 读取；无则 default
- session_id 由 chat/completions 在缺失时自动创建并返回 header X-Session-Id
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Literal, Union, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from api.errors import raise_api_error
from config.settings import settings
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.types import ChatCompletionMessageContentItem
from core.utils.user_context import get_user_id

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class ChatMessageMetaMap(BaseModel):
    """会话消息 meta 扩展字段。"""

    model_config = ConfigDict(extra="allow")


class ChatSessionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    title: str | None = None
    created_at: str
    updated_at: str
    last_model: str | None = None
    deleted_at: str | None = None


class ChatMessageRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    session_id: str
    role: str
    content: Union[str, List[ChatCompletionMessageContentItem]]
    created_at: str
    model: str | None = None
    meta: ChatMessageMetaMap | None = None


class ChatSessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[ChatSessionRecord]


class ChatMessageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: List[ChatMessageRecord]


class ChatSessionRenameResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: Literal[True] = True
    id: str
    title: str


class ChatSessionDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deleted: Literal[True] = True
    id: str


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


@router.get("", response_model=ChatSessionListResponse)
async def list_sessions(request: Request, limit: int = 50) -> ChatSessionListResponse:
    user_id = _get_user_id(request)
    rows = _store.list_sessions(user_id=user_id, limit=limit)
    return ChatSessionListResponse(data=[ChatSessionRecord.model_validate(r) for r in rows])


@router.get("/{session_id}/messages", response_model=ChatMessageListResponse)
async def list_messages(request: Request, session_id: str, limit: int = 200) -> ChatMessageListResponse:
    user_id = _get_user_id(request)
    rows = _store.list_messages(user_id=user_id, session_id=session_id, limit=limit)
    if rows == [] and not _store.session_exists(user_id=user_id, session_id=session_id):
        _raise_chat_session_not_found(session_id)
    return ChatMessageListResponse(data=[ChatMessageRecord.model_validate(r) for r in rows])


@router.patch("/{session_id}", response_model=ChatSessionRenameResponse)
async def rename_session(request: Request, session_id: str, title: str) -> ChatSessionRenameResponse:
    user_id = _get_user_id(request)
    ok = _store.rename_session(user_id=user_id, session_id=session_id, title=title)
    if not ok:
        _raise_chat_session_not_found(session_id)
    return ChatSessionRenameResponse(id=session_id, title=title)


@router.delete("/{session_id}", response_model=ChatSessionDeleteResponse)
async def delete_session(request: Request, session_id: str) -> ChatSessionDeleteResponse:
    user_id = _get_user_id(request)
    ok = _store.delete_session(user_id=user_id, session_id=session_id, hard=True)
    if not ok:
        _raise_chat_session_not_found(session_id)
    return ChatSessionDeleteResponse(id=session_id)

