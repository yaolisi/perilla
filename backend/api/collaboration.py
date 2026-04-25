"""
多 Agent 协作：按 correlation_id 聚合与 AgentSession 相关的轻量查询（Phase 0）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field

from core.agent_runtime.collaboration import STATE_KEY_COLLABORATION
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
