"""
V2.6: Observability & Replay Layer - Event API
提供事件流查询、回放和指标计算的 API
"""
from __future__ import annotations

import re
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, RootModel
from log import logger

from api.errors import APIException, raise_api_error

from core.data.base import db_session
from core.observability.prometheus_metrics import get_prometheus_business_metrics
from core.security.deps import require_authenticated_platform_admin
from core.system.runtime_settings import (
    get_events_api_require_authenticated,
    get_events_strict_workflow_binding,
)
from core.data.models.workflow import WorkflowExecutionORM
from core.utils.tenant_request import resolve_api_tenant_id

from execution_kernel.persistence.db import Database
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_store import ExecutionEventDB
from execution_kernel.events.event_types import ExecutionEventType
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.replay.replay_engine import ReplayEngine
from execution_kernel.analytics.metrics import MetricsCalculator
from sqlalchemy import select, distinct


def _enforce_events_api_authentication(request: Request) -> None:
    """生产向：与 system/mcp 一致要求 API Key + admin；可通过配置/env/系统设置关闭。"""
    if not get_events_api_require_authenticated():
        return
    require_authenticated_platform_admin(request)


def _observe_events_request(handler: str) -> None:
    try:
        get_prometheus_business_metrics().observe_events_api_request(handler=handler)
    except Exception:
        pass


router = APIRouter(
    prefix="/api/events",
    tags=["Events & Replay"],
    dependencies=[Depends(_enforce_events_api_authentication)],
)

# Agent session id：用于路径与 JSON 子串匹配；禁止 LIKE 元字符与注入畸形输入（生产向约束）
_AGENT_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_.@-]{1,128}$")


def _validate_agent_session_id_value(session_id: str) -> str:
    raw = session_id if isinstance(session_id, str) else ""
    if any(c.isspace() for c in raw):
        raise_api_error(
            status_code=400,
            code="events_invalid_agent_session_id",
            message="invalid agent session id",
            details={"reason": "whitespace_not_allowed"},
        )
    s = raw.strip()
    if not _AGENT_SESSION_ID_RE.fullmatch(s):
        raise_api_error(
            status_code=400,
            code="events_invalid_agent_session_id",
            message="invalid agent session id",
            details={"max_length": 128, "pattern": "alphanumeric, dot, underscore, hyphen, at"},
        )
    return s


def _payload_json_session_substring_like_pattern(normalized_session_id: str) -> str:
    """匹配 payload 中 \"session_id\": \"...\" 子串；对 LIKE 的 % _ \\ 转义。"""
    esc = (
        normalized_session_id.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%\"session_id\": \"{esc}\"%"


# =========================
# Response Models
# =========================


class EventPayload(BaseModel):
    """事件载荷（按事件类型变化，允许任意 JSON 对象键）。"""

    model_config = ConfigDict(extra="allow")


class GraphNodeStateSnapshot(BaseModel):
    """回放结果中单节点状态字典（结构随节点类型变化）。"""

    model_config = ConfigDict(extra="allow")


class ReplayGraphNodesMap(RootModel[Dict[str, GraphNodeStateSnapshot]]):
    """回放重建结果：节点 ID -> 节点状态快照。"""


class ReplayContextSnapshot(BaseModel):
    """回放结果中的上下文对象。"""

    model_config = ConfigDict(extra="allow")


class MetricsDetailsSnapshot(BaseModel):
    """指标接口 details 字段（计算器输出的结构化摘要）。"""

    model_config = ConfigDict(extra="allow")


class EventTypeBreakdownCounts(RootModel[Dict[str, int]]):
    """实例内事件类型 -> 出现次数。"""


class EventResponse(BaseModel):
    """单个事件响应"""
    event_id: str
    instance_id: str
    sequence: int
    event_type: str
    timestamp: int
    payload: EventPayload
    schema_version: int


class AgentSessionInstancesMap(RootModel[Dict[str, List[EventResponse]]]):
    """Agent Session 下各执行实例的事件列表（instance_id -> events）。"""


class EventListResponse(BaseModel):
    """事件列表响应"""
    instance_id: str
    total: int
    events: List[EventResponse]


class RebuiltStateResponse(BaseModel):
    """重建状态响应"""
    instance_id: str
    graph_id: str
    state: str
    nodes: ReplayGraphNodesMap
    context: ReplayContextSnapshot
    event_count: int
    last_sequence: int


class ValidationResponse(BaseModel):
    """验证响应"""
    valid: bool
    event_count: int
    node_count: int
    errors: List[str]
    first_sequence: Optional[int] = None
    last_sequence: Optional[int] = None


class MetricsResponse(BaseModel):
    """指标响应"""
    instance_id: str
    total_events: int
    node_success_rate: float
    avg_node_duration_ms: float
    total_retry_count: int
    total_execution_duration_ms: float
    completed_nodes: int
    failed_nodes: int
    details: MetricsDetailsSnapshot


class AgentSessionEventsResponse(BaseModel):
    """按 Agent Session 聚合的执行事件（instance_id -> 事件列表）"""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    instance_count: int
    instances: AgentSessionInstancesMap


class EventTypeBreakdownResponse(BaseModel):
    """实例内事件类型计数"""

    model_config = ConfigDict(extra="forbid")

    instance_id: str
    total_events: int
    breakdown: EventTypeBreakdownCounts


def _graph_instance_visible_to_tenant(instance_id: str, tenant_id: str) -> bool:
    """
    workflow_executions 无记录：默认 True（仅有 execution_event 的调试路径）；
    get_events_strict_workflow_binding() 为 True 时改为 False（系统设置 / .env 可配）。
    有记录则 tenant_id 必须一致。
    """
    tid = (tenant_id or "").strip() or "default"
    with db_session() as db:
        row = (
            db.query(WorkflowExecutionORM)
            .filter(WorkflowExecutionORM.graph_instance_id == instance_id)
            .first()
        )
        if row is None:
            if get_events_strict_workflow_binding():
                return False
            return True
        row_tid = str(row.tenant_id or "default").strip() or "default"
        return row_tid == tid


def _require_graph_instance_tenant_scope(instance_id: str, tenant_id: str) -> None:
    """
    若 workflow_executions 中已有该 graph_instance_id，则仅允许归属租户访问。
    无 ORM 记录时不拦截（兼容仅有 execution_event 行的调试路径）。
    """
    if not _graph_instance_visible_to_tenant(instance_id, tenant_id):
        raise_api_error(
            status_code=404,
            code="execution_instance_not_found",
            message="instance not found",
            details={"instance_id": instance_id},
        )


# =========================
# Helper
# =========================

def _get_db() -> Database:
    """获取数据库实例"""
    return Database()


def _event_to_response(event: ExecutionEvent) -> EventResponse:
    """转换事件为响应模型"""
    return EventResponse(
        event_id=event.event_id,
        instance_id=event.instance_id,
        sequence=event.sequence,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        payload=EventPayload.model_validate(event.payload),
        schema_version=event.schema_version,
    )


# =========================
# Events API
# =========================

@router.get("/instance/{instance_id}", response_model=EventListResponse)
async def get_instance_events(
    instance_id: str,
    request: Request,
    start_sequence: Annotated[int, Query(ge=1, description="起始序列号")] = 1,
    end_sequence: Annotated[Optional[int], Query(ge=1, description="结束序列号")] = None,
) -> EventListResponse:
    """
    获取实例的事件流
    
    Args:
        instance_id: 图实例 ID
        start_sequence: 起始序列号（默认 1）
        end_sequence: 结束序列号（默认到最后）
    
    Returns:
        事件列表（按序列号排序）
    """
    try:
        _observe_events_request("instance")
        _require_graph_instance_tenant_scope(instance_id, resolve_api_tenant_id(request))
        db = _get_db()
        
        async with db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(
                instance_id=instance_id,
                start_sequence=start_sequence,
                end_sequence=end_sequence,
            )
            
            return EventListResponse(
                instance_id=instance_id,
                total=len(events),
                events=[_event_to_response(e) for e in events],
            )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get events for instance {instance_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"instance_id": instance_id, "operation": "get_instance_events"},
        )
        raise AssertionError("unreachable")


@router.get("/agent-session/{session_id}")
async def get_agent_session_events(
    session_id: str,
    request: Request,
    limit_instances: Annotated[int, Query(ge=1, le=100, description="最多返回的实例数")] = 20,
) -> AgentSessionEventsResponse:
    """
    按 Agent Session 聚合查询执行事件。

    通过 GraphStarted 事件 payload.initial_context.session_id 反查相关 instance。
    """
    try:
        _observe_events_request("agent_session")
        sid_val = _validate_agent_session_id_value(session_id)
        tenant_id = resolve_api_tenant_id(request)
        db = _get_db()
        like_pat = _payload_json_session_substring_like_pattern(sid_val)
        async with db.async_session() as session:
            rows = await session.execute(
                select(distinct(ExecutionEventDB.instance_id))
                .where(ExecutionEventDB.payload_json.like(like_pat, escape="\\"))
                .order_by(ExecutionEventDB.instance_id.desc())
                .limit(limit_instances)
            )
            raw_instance_ids = [r[0] for r in rows.fetchall() if r and r[0]]
            instance_ids = [
                iid for iid in raw_instance_ids if _graph_instance_visible_to_tenant(iid, tenant_id)
            ]
            store = EventStore(session)
            out: Dict[str, List[EventResponse]] = {}
            for instance_id in instance_ids:
                events = await store.get_events(instance_id=instance_id, start_sequence=1, end_sequence=None)
                out[instance_id] = [_event_to_response(e) for e in events]
            return AgentSessionEventsResponse(
                session_id=sid_val,
                instance_count=len(instance_ids),
                instances=AgentSessionInstancesMap(out),
            )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get events by session {session_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"session_id": session_id, "operation": "get_agent_session_events"},
        )
        raise AssertionError("unreachable")


@router.get("/instance/{instance_id}/event-types")
async def get_event_type_breakdown(instance_id: str, request: Request) -> EventTypeBreakdownResponse:
    """
    获取实例的事件类型分布
    
    Returns:
        各事件类型的数量统计
    """
    try:
        _observe_events_request("event_types")
        _require_graph_instance_tenant_scope(instance_id, resolve_api_tenant_id(request))
        db = _get_db()
        
        async with db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id)
            
            breakdown: Dict[str, int] = {}
            for event in events:
                event_type = event.event_type.value
                breakdown[event_type] = breakdown.get(event_type, 0) + 1

            return EventTypeBreakdownResponse(
                instance_id=instance_id,
                total_events=len(events),
                breakdown=EventTypeBreakdownCounts(breakdown),
            )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event breakdown for instance {instance_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"instance_id": instance_id, "operation": "get_event_type_breakdown"},
        )
        raise AssertionError("unreachable")


# =========================
# Replay API
# =========================

@router.get("/instance/{instance_id}/replay", response_model=RebuiltStateResponse)
async def replay_instance_state(
    instance_id: str,
    request: Request,
    target_sequence: Annotated[Optional[int], Query(ge=1, description="目标序列号（用于断点调试）")] = None,
) -> RebuiltStateResponse:
    """
    回放实例状态
    
    从事件流重建执行状态，用于 Debug 和审计。
    
    Args:
        instance_id: 图实例 ID
        target_sequence: 目标序列号（可选，用于断点调试）
    
    Returns:
        重建的图状态
    """
    try:
        _observe_events_request("replay")
        _require_graph_instance_tenant_scope(instance_id, resolve_api_tenant_id(request))
        db = _get_db()
        
        async with db.async_session() as session:
            engine = ReplayEngine(session)
            
            if target_sequence:
                state = await engine.replay_to_point(instance_id, target_sequence)
            else:
                state = await engine.rebuild_instance(instance_id)
            
            return RebuiltStateResponse(
                instance_id=state.instance_id,
                graph_id=state.graph_id,
                state=state.state,
                nodes=ReplayGraphNodesMap(
                    {k: GraphNodeStateSnapshot.model_validate(v.to_dict()) for k, v in state.nodes.items()}
                ),
                context=ReplayContextSnapshot.model_validate(state.context),
                event_count=state.event_count,
                last_sequence=state.last_sequence,
            )
    except APIException:
        raise
    except ValueError as e:
        raise_api_error(
            status_code=404,
            code="events_replay_not_found",
            message=str(e),
            details={"instance_id": instance_id},
        )
        raise AssertionError("unreachable")
    except Exception as e:
        logger.error(f"Failed to replay instance {instance_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"instance_id": instance_id, "operation": "replay_instance_state"},
        )
        raise AssertionError("unreachable")


@router.get("/instance/{instance_id}/validate", response_model=ValidationResponse)
async def validate_event_stream(instance_id: str, request: Request) -> ValidationResponse:
    """
    验证事件流完整性
    
    检查：
    - 序列号连续性
    - 必须有 GraphStarted
    - 必须有终止事件
    - Node 状态转换合法性
    
    Returns:
        验证报告
    """
    try:
        _observe_events_request("validate")
        _require_graph_instance_tenant_scope(instance_id, resolve_api_tenant_id(request))
        db = _get_db()
        
        async with db.async_session() as session:
            engine = ReplayEngine(session)
            validation = await engine.validate_event_stream(instance_id)
            
            return ValidationResponse(
                valid=validation["valid"],
                event_count=validation.get("event_count", 0),
                node_count=validation.get("node_count", 0),
                errors=validation.get("errors", []),
                first_sequence=validation.get("first_sequence"),
                last_sequence=validation.get("last_sequence"),
            )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate event stream for instance {instance_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"instance_id": instance_id, "operation": "validate_event_stream"},
        )
        raise AssertionError("unreachable")


# =========================
# Metrics API
# =========================

@router.get("/instance/{instance_id}/metrics", response_model=MetricsResponse)
async def get_instance_metrics(instance_id: str, request: Request) -> MetricsResponse:
    """
    获取实例执行指标
    
    从事件流计算执行指标，用于离线分析。
    
    Returns:
        执行指标
    """
    try:
        _observe_events_request("metrics")
        _require_graph_instance_tenant_scope(instance_id, resolve_api_tenant_id(request))
        db = _get_db()
        
        async with db.async_session() as session:
            calculator = MetricsCalculator(session)
            metrics = await calculator.compute_metrics(instance_id)
            
            return MetricsResponse(
                instance_id=metrics.instance_id,
                total_events=metrics.total_events,
                node_success_rate=metrics.node_success_rate,
                avg_node_duration_ms=metrics.avg_node_duration_ms,
                total_retry_count=metrics.total_retry_count,
                total_execution_duration_ms=metrics.total_execution_duration_ms,
                completed_nodes=metrics.completed_nodes,
                failed_nodes=metrics.failed_nodes,
                details=MetricsDetailsSnapshot.model_validate(metrics.details),
            )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metrics for instance {instance_id}: {e}")
        raise_api_error(
            status_code=500,
            code="events_internal_error",
            message=str(e),
            details={"instance_id": instance_id, "operation": "get_instance_metrics"},
        )
        raise AssertionError("unreachable")
