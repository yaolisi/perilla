"""
多 Agent 协作：按 correlation_id 聚合与 AgentSession 相关的轻量查询（Phase 0）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field

from api.errors import raise_api_error
from core.agent_runtime.collaboration import (
    STATE_KEY_COLLABORATION,
    STATE_KEY_COLLABORATION_MESSAGES,
    append_collaboration_message_to_state,
    build_collaboration_message,
)
from core.agent_runtime.session import get_agent_session_store
from core.security.deps import require_authenticated_platform_admin

router = APIRouter(
    prefix="/api/collaboration",
    tags=["collaboration"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)


class SessionCollaborationItem(BaseModel):
    session_id: str
    agent_id: str
    status: str
    kernel_instance_id: Optional[str] = None
    collaboration: Dict[str, Any] = Field(default_factory=dict)


class CorrelationSummaryResponse(BaseModel):
    correlation_id: str
    sessions: List[SessionCollaborationItem]
    note: str = (
        "从当前用户最近若干条会话中筛选 state.collaboration.correlation_id；"
        "生产环境可后续换为 DB 索引或 L3 协作表。"
    )


class CollaborationMessageUpsertRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    sender: str = Field(..., min_length=1, max_length=128)
    receiver: str = Field(..., min_length=1, max_length=128)
    task_id: str = Field(..., min_length=1, max_length=128)
    content: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = Field(default=None, max_length=32)
    timestamp: Optional[str] = None
    message_id: Optional[str] = Field(default=None, max_length=128)
    meta: Optional[Dict[str, Any]] = None


class CollaborationMessageListResponse(BaseModel):
    correlation_id: str
    total: int
    messages: List[Dict[str, Any]]


def _get_user_id(request: Request) -> str:
    uid = (request.headers.get("X-User-Id") or "").strip()
    return uid or "default"


def _match_collaboration_sessions(
    rows: Sequence[Any],
    *,
    correlation_id: str,
    orch_filter: Optional[str],
) -> List[SessionCollaborationItem]:
    cid = (correlation_id or "").strip()
    out: List[SessionCollaborationItem] = []
    for s in rows:
        st = s.state or {}
        block = st.get(STATE_KEY_COLLABORATION) if isinstance(st, dict) else None
        if not isinstance(block, dict):
            continue
        if (block.get("correlation_id") or "").strip() != cid:
            continue
        if orch_filter is not None and (block.get("orchestrator_agent_id") or "").strip() != orch_filter:
            continue
        out.append(
            SessionCollaborationItem(
                session_id=s.session_id,
                agent_id=s.agent_id,
                status=s.status,
                kernel_instance_id=getattr(s, "kernel_instance_id", None),
                collaboration=block,
            )
        )
    return out


def _extract_messages_from_rows(
    rows: Sequence[Any],
    *,
    correlation_id: str,
    task_id: Optional[str],
    limit_messages: int,
) -> List[Dict[str, Any]]:
    cid = (correlation_id or "").strip()
    task_filter = (task_id or "").strip() or None
    out: List[Dict[str, Any]] = []
    for s in rows:
        out.extend(_messages_from_session_row(s, correlation_id=cid, task_filter=task_filter))
    out.sort(key=lambda x: str(x.get("timestamp") or ""))
    cap = max(1, min(limit_messages, 2000))
    return out[-cap:]


def _messages_from_session_row(
    row: Any,
    *,
    correlation_id: str,
    task_filter: Optional[str],
) -> List[Dict[str, Any]]:
    st = row.state or {}
    block = st.get(STATE_KEY_COLLABORATION) if isinstance(st, dict) else None
    if not isinstance(block, dict):
        return []
    if (block.get("correlation_id") or "").strip() != correlation_id:
        return []
    messages = block.get(STATE_KEY_COLLABORATION_MESSAGES)
    if not isinstance(messages, list):
        return []
    out: List[Dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if task_filter is not None and (m.get("task_id") or "").strip() != task_filter:
            continue
        out.append(m)
    return out


@router.get(
    "/correlation/{correlation_id}",
    summary="按协作 correlation 列出智能体会话",
    response_description="当前用户下、最近 limit 条会话中匹配 collaboration 的记录",
)
async def get_sessions_by_correlation(
    correlation_id: str,
    request: Request,
    limit: int = 200,
    orchestrator_agent_id: Optional[str] = None,
) -> CorrelationSummaryResponse:
    """
    列出 `AgentSession.state["collaboration"].correlation_id` 与路径参数相等的会话（`X-User-Id` 隔离）。

    - `limit`：最多扫描最近 N 条会话（默认 200，最大 500）。
    - `orchestrator_agent_id`：若提供，则再要求协作块中 `orchestrator_agent_id` 与其一致（多 Agent 链过滤）。
    """
    cid = (correlation_id or "").strip()
    orch_filter = (orchestrator_agent_id or "").strip() or None
    store = get_agent_session_store()
    user_id = _get_user_id(request)
    cap = max(1, min(limit, 500))
    rows = store.list_sessions(user_id=user_id, limit=cap, agent_id=None)
    out = _match_collaboration_sessions(rows, correlation_id=cid, orch_filter=orch_filter)
    return CorrelationSummaryResponse(correlation_id=cid, sessions=out)


@router.post("/messages", summary="写入协作消息")
async def upsert_collaboration_message(
    body: CollaborationMessageUpsertRequest,
    request: Request,
) -> Dict[str, Any]:
    store = get_agent_session_store()
    user_id = _get_user_id(request)
    session = store.get_session(body.session_id)
    if session is None or session.user_id != user_id:
        raise_api_error(status_code=404, code="collaboration_session_not_found", message="session not found")

    state = session.state if isinstance(session.state, dict) else {}
    collab = state.get(STATE_KEY_COLLABORATION) if isinstance(state, dict) else None
    if not isinstance(collab, dict):
        collab = {"correlation_id": body.correlation_id, "orchestrator_agent_id": body.sender, "invoked_from": {"type": "api"}}
    existing_cid = str(collab.get("correlation_id") or "").strip()
    if existing_cid and existing_cid != body.correlation_id:
        raise_api_error(
            status_code=400,
            code="collaboration_correlation_mismatch",
            message="session correlation_id does not match payload",
            details={"session_correlation_id": existing_cid, "payload_correlation_id": body.correlation_id},
        )

    message = build_collaboration_message(body.model_dump(exclude_none=True))
    session.state = append_collaboration_message_to_state(state, message)
    if not store.save_session(session):
        raise_api_error(status_code=500, code="collaboration_message_persist_failed", message="failed to save collaboration message")
    return {"success": True, "correlation_id": body.correlation_id, "message": message}


@router.get("/correlation/{correlation_id}/messages", summary="回放协作消息")
async def list_collaboration_messages(
    correlation_id: str,
    request: Request,
    limit_sessions: int = 200,
    limit_messages: int = 500,
    task_id: Optional[str] = None,
) -> CollaborationMessageListResponse:
    store = get_agent_session_store()
    user_id = _get_user_id(request)
    session_cap = max(1, min(limit_sessions, 500))
    rows = store.list_sessions(user_id=user_id, limit=session_cap, agent_id=None)
    messages = _extract_messages_from_rows(
        rows,
        correlation_id=correlation_id,
        task_id=task_id,
        limit_messages=limit_messages,
    )
    return CollaborationMessageListResponse(
        correlation_id=(correlation_id or "").strip(),
        total=len(messages),
        messages=messages,
    )
