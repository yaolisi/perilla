"""
Workflow API Endpoints

Workflow Control Plane 的 REST API 接口。
"""

from typing import Annotated, List, Literal, Optional, Dict, Any, Union, AsyncIterator, Callable, cast
import asyncio
import io
import json
import hashlib
import zipfile
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, Query, status, BackgroundTasks, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, RootModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from core.workflows.models import (
    Workflow,
    WorkflowVersion,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionNode,
    WorkflowExecutionNodeState,
    WorkflowLifecycleState,
    WorkflowVersionState,
    WorkflowExecutionState,
    WorkflowDAG,
    WorkflowNode,
    WorkflowEdge,
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
    WorkflowExecutionCreateRequest
)
from core.workflows.services import (
    WorkflowService,
    WorkflowVersionService,
    WorkflowExecutionService,
    WorkflowApprovalService,
)
from core.workflows.repository import WorkflowGovernanceAuditRepository
from core.workflows.governance import get_execution_manager, QuotaConfig
from core.workflows.recommendation import WorkflowToolCompositionRecommender
from core.workflows.runtime import WorkflowRuntime
from core.workflows.debug_runtime import (
    kernel_debug_snapshot as _kernel_debug_snapshot_helper,
    recent_events_debug as _recent_events_debug_helper,
)
from core.workflows.tenant_guard import namespace_matches_tenant
from core.utils.tenant_request import resolve_api_tenant_id
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from config.settings import settings
from middleware.user_context import get_current_user
from core.data.base import get_db, get_engine, sessionmaker_for_engine
from core.idempotency.service import IdempotencyService
from api.error_i18n import localize_error_message, resolve_accept_language_for_sse
from api.errors import raise_api_error
from log import logger
from execution_kernel.persistence.db import Database
from execution_kernel.events.event_store import EventStore
from execution_kernel.events.event_model import ExecutionEvent
from execution_kernel.events.event_types import ExecutionEventType

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
_WORKFLOW_BG_TASKS: set[asyncio.Task] = set()
_WORKFLOW_BG_TASK_BY_EXECUTION: Dict[str, asyncio.Task] = {}
_TERMINAL_RECONCILE_LOCK_UNTIL: Dict[str, datetime] = {}
MSG_WORKFLOW_NOT_FOUND = "Workflow not found"
MSG_ACCESS_DENIED = "Access denied"
MSG_VERSION_NOT_FOUND = "Version not found"
MSG_EXECUTION_NOT_FOUND = "Execution not found"
MSG_ADMIN_ACCESS_REQUIRED = "Admin access required"
FAILURE_REPORT_SCHEMA_VERSION = "1.1"
SSE_STATUS_DELTA_SCHEMA_VERSION = 1
SSE_STREAM_RESOURCE_NOT_FOUND_ERROR_CODE = "sse_stream_resource_not_found"
SSE_STREAM_RUNTIME_ERROR_CODE = "sse_stream_runtime_error"
SENSITIVE_FIELD_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
}


def _ensure_workflow_tenant(workflow: Optional[Workflow], tenant_id: str) -> Workflow:
    if workflow is None:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
        )
        raise AssertionError("unreachable")
    if not namespace_matches_tenant(getattr(workflow, "namespace", None), tenant_id):
        # 404 避免泄露跨租户资源存在性
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
        )
        raise AssertionError("unreachable")
    return workflow


class WorkflowJsonMap(BaseModel):
    """工作流 API 中的自由 JSON 对象（参数、上下文、配置片段等）。"""

    model_config = ConfigDict(extra="allow")


class WorkflowJsonRecord(BaseModel):
    """工作流 API 中的自由 JSON 对象列表项（时间线行、节点摘要等）。"""

    model_config = ConfigDict(extra="allow")


def _as_workflow_json_map(data: Any) -> WorkflowJsonMap:
    if isinstance(data, WorkflowJsonMap):
        return data
    if isinstance(data, dict):
        return WorkflowJsonMap.model_validate(data)
    return WorkflowJsonMap()


def _as_optional_workflow_json_map(data: Any) -> Optional[WorkflowJsonMap]:
    if data is None:
        return None
    if isinstance(data, WorkflowJsonMap):
        return data
    if isinstance(data, dict):
        return WorkflowJsonMap.model_validate(data)
    return None


def _as_workflow_json_records(items: Optional[List[Any]]) -> List[WorkflowJsonRecord]:
    out: List[WorkflowJsonRecord] = []
    if not items:
        return out
    for it in items:
        if isinstance(it, WorkflowJsonRecord):
            out.append(it)
        elif isinstance(it, dict):
            out.append(WorkflowJsonRecord.model_validate(it))
    return out


# ==================== Response Models ====================

class WorkflowResponse(BaseModel):
    id: str
    namespace: str
    name: str
    description: Optional[str] = None
    lifecycle_state: str
    latest_version_id: Optional[str] = None
    published_version_id: Optional[str] = None
    owner_id: str
    tags: List[str]
    created_at: str
    updated_at: str


class WorkflowVersionResponse(BaseModel):
    version_id: str
    workflow_id: str
    version_number: str
    state: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    published_by: Optional[str] = None
    created_at: str
    published_at: Optional[str] = None


class WorkflowExecutionResponse(BaseModel):
    execution_id: str
    workflow_id: str
    version_id: str
    state: str
    graph_instance_id: Optional[str] = None
    input_data: WorkflowJsonMap
    output_data: Optional[WorkflowJsonMap] = None
    global_context: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    trigger_type: str = "manual"
    triggered_by: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[WorkflowJsonMap] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    queue_position: Optional[int] = None
    queued_at: Optional[str] = None
    wait_duration_ms: Optional[int] = None
    node_states: List[WorkflowJsonRecord] = Field(default_factory=list)
    node_timeline: List[WorkflowJsonRecord] = Field(default_factory=list)
    replay: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    agent_summaries: List[WorkflowJsonRecord] = Field(default_factory=list)


class WorkflowExecutionStatusResponse(BaseModel):
    execution_id: str
    workflow_id: str
    version_id: str
    state: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    queue_position: Optional[int] = None
    wait_duration_ms: Optional[int] = None
    node_timeline: List[WorkflowJsonRecord] = Field(default_factory=list)


class WorkflowApprovalTaskResponse(BaseModel):
    id: str
    execution_id: str
    workflow_id: str
    node_id: str
    title: Optional[str] = None
    reason: Optional[str] = None
    payload: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    status: str
    requested_by: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None
    created_at: Optional[str] = None
    execution_state_after_decision: Optional[str] = None


class WorkflowApprovalListResponse(BaseModel):
    execution_id: str
    execution_state: Optional[str] = None
    items: List[WorkflowApprovalTaskResponse] = Field(default_factory=list)


class WorkflowGovernanceConfigRequest(BaseModel):
    max_queue_size: Optional[int] = Field(default=None, ge=1, le=10000)
    backpressure_strategy: Optional[str] = Field(default=None, description="wait or reject")


class ToolCompositionUsageRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=128)
    tool_sequence: List[str] = Field(default_factory=list, max_length=200)


class ToolCompositionRecommendItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str
    tools: List[str]
    score: int
    signals: WorkflowJsonMap


class ToolCompositionRecommendResponse(BaseModel):
    items: List[ToolCompositionRecommendItem]
    total: int


class WorkflowListEnvelope(BaseModel):
    items: List[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowVersionListEnvelope(BaseModel):
    items: List[WorkflowVersionResponse]
    total: int
    limit: int
    offset: int


class WorkflowExecutionListEnvelope(BaseModel):
    items: List[WorkflowExecutionResponse]
    total: int
    limit: int
    offset: int


class WorkflowExecutionErrorLogRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    execution_id: str
    event_id: str
    sequence: int
    timestamp: str
    node_id: str
    event_type: str
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    error_stack: Optional[str] = None
    failure_strategy: Optional[str] = None
    retry_count: int = 0


class WorkflowExecutionErrorLogsListEnvelope(BaseModel):
    items: List[WorkflowExecutionErrorLogRow]
    total: int
    limit: int
    offset: int


class WorkflowGovernanceAuditEntry(BaseModel):
    id: str
    workflow_id: str
    changed_by: Optional[str] = None
    old_config: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    new_config: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    created_at: Optional[str] = None


class WorkflowGovernanceAuditListEnvelope(BaseModel):
    items: List[WorkflowGovernanceAuditEntry]
    total: int
    limit: int
    offset: int


class WorkflowContractDiffPolicy(BaseModel):
    required_input_added_breaking: bool
    output_added_risky: bool
    block_publish_on_breaking: bool


class WorkflowContractDiffResponse(BaseModel):
    breaking_changes: List[str]
    risky_changes: List[str]
    info_changes: List[str]
    exempt_fields: List[str]
    policy: WorkflowContractDiffPolicy


class WorkflowSubworkflowImpactRow(BaseModel):
    workflow_id: str
    version_id: str
    version_number: str
    version_state: str
    node_id: str
    reference_mode: str
    reference_version_id: Optional[str] = None
    reference_version: Optional[str] = None
    impact_kind: str
    risk_level: str
    impact_reason: str


class WorkflowSubworkflowRiskSummary(RootModel[Dict[str, int]]):
    """子工作流影响分析的风险等级计数（breaking / compatible / risky / info 等可扩展键）。"""


class WorkflowSubworkflowImpactResponse(BaseModel):
    target_workflow_id: str
    target_version_id: Optional[str] = None
    target_version_number: Optional[str] = None
    baseline_version_id: Optional[str] = None
    baseline_version_number: Optional[str] = None
    include_only_published: bool
    contract_diff: WorkflowContractDiffResponse
    total_impacted: int
    risk_summary: WorkflowSubworkflowRiskSummary
    impacted: List[WorkflowSubworkflowImpactRow]


class WorkflowVersionsDiffSummaryCounts(BaseModel):
    node_added: int
    node_removed: int
    node_changed: int
    edge_added: int
    edge_removed: int


class WorkflowVersionsCompareNodesDiff(BaseModel):
    added: List[str]
    removed: List[str]
    changed: List[str]


class WorkflowVersionsCompareEdgesDiff(BaseModel):
    added: List[str]
    removed: List[str]


class WorkflowVersionsCompareResponse(BaseModel):
    workflow_id: str
    from_version_id: str
    to_version_id: str
    summary: WorkflowVersionsDiffSummaryCounts
    nodes: WorkflowVersionsCompareNodesDiff
    edges: WorkflowVersionsCompareEdgesDiff


class WorkflowVersionDetailResponse(WorkflowVersionResponse):
    dag: WorkflowDAG
    checksum: str


class WorkflowFailureReportFilterSnapshot(BaseModel):
    selected_node_id: Optional[str] = None
    error_type: Optional[str] = None
    failure_strategy: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class WorkflowExecutionFailureReportResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    report_schema_version: str
    exported_at: str
    workflow_id: str
    execution_id: str
    execution_state: str
    trigger_type: str
    triggered_by: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    queue_position: Optional[int] = None
    wait_duration_ms: Optional[int] = None
    global_context: WorkflowJsonMap = Field(default_factory=WorkflowJsonMap)
    global_error_details: Optional[WorkflowJsonMap] = None
    recovery_actions: List[WorkflowJsonRecord] = Field(default_factory=list)
    node_timeline: List[WorkflowJsonRecord] = Field(default_factory=list)
    node_states: List[WorkflowJsonRecord] = Field(default_factory=list)
    filtered_error_logs: List[WorkflowJsonRecord] = Field(default_factory=list)
    filter_snapshot: WorkflowFailureReportFilterSnapshot
    execution: WorkflowExecutionResponse
    redaction_applied: bool = False
    redacted_key_count: int = 0
    report_sha256: Optional[str] = None


class WorkflowExecutionCallChainItem(BaseModel):
    execution_id: str
    workflow_id: str
    version_id: str
    state: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    parent_execution_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    correlation_id: Optional[str] = None
    recovery_summaries: List[WorkflowJsonRecord] = Field(default_factory=list)
    collaboration_summaries: List[WorkflowJsonRecord] = Field(default_factory=list)


class WorkflowExecutionCallChainResponse(BaseModel):
    root_execution_id: str
    correlation_id: str
    items: List[WorkflowExecutionCallChainItem]
    total: int


class WorkflowExecutionDebugBundle(BaseModel):
    graph_instance_id: Optional[str] = None
    replay_hint: str = ""


class WorkflowExecutionDebugResponse(BaseModel):
    execution: WorkflowExecutionResponse
    kernel_snapshot: Optional[WorkflowJsonMap] = None
    recent_events: List[WorkflowJsonRecord] = Field(default_factory=list)
    debug: WorkflowExecutionDebugBundle


class WorkflowGovernanceConcurrencyStatus(BaseModel):
    active_slots: int


class WorkflowGovernanceQueueStatus(BaseModel):
    queued_executions: int
    max_queue_size: int
    backpressure_strategy: str
    recent_reject_count: int
    average_wait_ms: Optional[int] = None


class WorkflowGovernanceStatusResponse(BaseModel):
    quota: WorkflowJsonMap
    concurrency: WorkflowGovernanceConcurrencyStatus
    queue: WorkflowGovernanceQueueStatus


class ToolCompositionUsageRecordedResponse(BaseModel):
    ok: Literal[True] = True


def _extract_idempotency_key(http_request: Request) -> Optional[str]:
    key = (
        http_request.headers.get("Idempotency-Key")
        or http_request.headers.get("X-Idempotency-Key")
        or http_request.headers.get("X-Request-Id")
    )
    if not key:
        return None
    key = key.strip()
    return key[:256] if key else None


def _stable_request_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _approval_task_to_response(row: Any, execution_state_after_decision: Optional[str] = None) -> WorkflowApprovalTaskResponse:
    return WorkflowApprovalTaskResponse(
        id=row.id,
        execution_id=row.execution_id,
        workflow_id=row.workflow_id,
        node_id=row.node_id,
        title=row.title,
        reason=row.reason,
        payload=_as_workflow_json_map(row.payload or {}),
        status=row.status,
        requested_by=row.requested_by,
        decided_by=row.decided_by,
        decided_at=row.decided_at.isoformat() if row.decided_at else None,
        created_at=row.created_at.isoformat() if row.created_at else None,
        execution_state_after_decision=execution_state_after_decision,
    )


# ==================== Workflow Endpoints ====================

@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    http_request: Request,
    request: WorkflowCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowResponse:
    """创建工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    if request.namespace and request.namespace != tenant_id:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_namespace_tenant_mismatch",
            message="namespace must match tenant",
            details={"tenant_id": tenant_id, "namespace": request.namespace},
        )
    request = request.model_copy(update={"namespace": tenant_id})
    service = WorkflowService(db)
    try:
        workflow = service.create_workflow(request, current_user)
        return _workflow_to_response(workflow)
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_409_CONFLICT,
            code="workflow_conflict",
            message=str(e),
        )
        raise AssertionError("unreachable")


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    http_request: Request,
    workflow_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowResponse:
    """获取工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    service = WorkflowService(db)
    workflow = service.get_workflow(workflow_id, tenant_id=tenant_id)
    
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")

    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    
    return _workflow_to_response(workflow)


@router.get("", response_model=WorkflowListEnvelope)
async def list_workflows(
    http_request: Request,
    namespace: Optional[str] = None,
    lifecycle_state: Optional[WorkflowLifecycleState] = None,
    limit: Annotated[int, Query(le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowListEnvelope:
    """列出工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    if namespace and namespace != tenant_id:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_namespace_tenant_mismatch",
            message="namespace must match tenant",
            details={"tenant_id": tenant_id, "namespace": namespace},
        )
    namespace = tenant_id
    service = WorkflowService(db)
    workflows = service.list_workflows(
        namespace=namespace,
        tenant_id=tenant_id,
        owner_id=current_user,
        lifecycle_state=lifecycle_state,
        limit=limit,
        offset=offset
    )
    total = service.count_workflows(
        namespace=namespace,
        tenant_id=tenant_id,
        owner_id=current_user,
        lifecycle_state=lifecycle_state,
    )
    
    return WorkflowListEnvelope(
        items=[_workflow_to_response(w) for w in workflows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    http_request: Request,
    workflow_id: str,
    request: WorkflowUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowResponse:
    """更新工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    service = WorkflowService(db)
    existing = service.get_workflow(workflow_id, tenant_id=tenant_id)
    if existing:
        existing = _ensure_workflow_tenant(existing, tenant_id)
    
    try:
        workflow = service.update_workflow(workflow_id, request, current_user, tenant_id=tenant_id)
        if not workflow:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_not_found",
                message=MSG_WORKFLOW_NOT_FOUND,
                details={"workflow_id": workflow_id},
            )
            raise AssertionError("unreachable")
        return _workflow_to_response(workflow)
    except PermissionError as e:
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=str(e),
            details={"workflow_id": workflow_id, "action": "write"},
        )
        raise AssertionError("unreachable")
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_invalid_request",
            message=str(e),
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    http_request: Request,
    workflow_id: str,
    hard: Annotated[bool, Query(description="Hard delete")] = False,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> None:
    """删除工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    service = WorkflowService(db)
    existing = service.get_workflow(workflow_id, tenant_id=tenant_id)
    if existing:
        existing = _ensure_workflow_tenant(existing, tenant_id)
    
    try:
        result = service.delete_workflow(workflow_id, current_user, soft=not hard, tenant_id=tenant_id)
        if not result:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_not_found",
                message=MSG_WORKFLOW_NOT_FOUND,
                details={"workflow_id": workflow_id},
            )
    except PermissionError as e:
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=str(e),
            details={"workflow_id": workflow_id, "action": "delete"},
        )
        raise AssertionError("unreachable")


@router.post("/{workflow_id}/publish", response_model=WorkflowResponse)
async def publish_workflow(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowResponse:
    """发布工作流"""
    tenant_id = resolve_api_tenant_id(http_request)
    service = WorkflowService(db)
    existing = service.get_workflow(workflow_id, tenant_id=tenant_id)
    if existing:
        existing = _ensure_workflow_tenant(existing, tenant_id)
    
    try:
        workflow = service.publish_workflow(workflow_id, version_id, current_user, tenant_id=tenant_id)
        if not workflow:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_not_found",
                message=MSG_WORKFLOW_NOT_FOUND,
                details={"workflow_id": workflow_id},
            )
            raise AssertionError("unreachable")
        return _workflow_to_response(workflow)
    except PermissionError as e:
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=str(e),
            details={"workflow_id": workflow_id, "action": "publish"},
        )
        raise AssertionError("unreachable")


# ==================== Version Endpoints ====================

class WorkflowVersionCreateBody(BaseModel):
    dag: WorkflowDAG
    version_number: Optional[str] = None
    description: Optional[str] = None


class WorkflowVersionRollbackBody(BaseModel):
    publish: bool = True
    description: Optional[str] = None


@router.post("/{workflow_id}/versions", response_model=WorkflowVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    http_request: Request,
    workflow_id: str,
    request: WorkflowVersionCreateBody,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowVersionResponse:
    """创建工作流版本"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "write"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "write"},
        )
    
    # 创建定义
    version_service = WorkflowVersionService(db)
    definition = version_service.create_definition(
        workflow_id=workflow_id,
        description=request.description,
        created_by=current_user
    )
    
    # 创建版本
    try:
        version = version_service.create_version(
            workflow_id=workflow_id,
            definition_id=definition.definition_id,
            dag=request.dag,
            version_number=request.version_number,
            description=request.description,
            created_by=current_user
        )
        
        # 更新工作流的 latest_version_id
        workflow_service.repository.update(
            workflow_id,
            {"latest_version_id": version.version_id},
            current_user,
        )
        
        return _version_to_response(version)
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_version_invalid_request",
            message=str(e),
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionListEnvelope)
async def list_versions(
    http_request: Request,
    workflow_id: str,
    state: Optional[WorkflowVersionState] = None,
    limit: Annotated[int, Query(le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowVersionListEnvelope:
    """列出工作流版本"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    
    version_service = WorkflowVersionService(db)
    versions = version_service.list_versions(
        workflow_id=workflow_id,
        state=state,
        limit=limit,
        offset=offset
    )
    total = version_service.count_versions(
        workflow_id=workflow_id,
        state=state,
    )
    
    return WorkflowVersionListEnvelope(
        items=[_version_to_response(v) for v in versions],
        total=total,
        limit=limit,
        offset=offset,
    )


# 必须在 /{version_id} 之前注册，避免与版本详情路由冲突。
@router.get("/{workflow_id}/impact", response_model=WorkflowSubworkflowImpactResponse)
async def get_workflow_impact(
    http_request: Request,
    workflow_id: str,
    target_version_id: Annotated[Optional[str], Query(description="指定版本ID进行影响分析")] = None,
    baseline_version_id: Annotated[Optional[str], Query(description="对比基线版本ID，可选")] = None,
    published_only: Annotated[bool, Query(description="仅分析已发布版本")] = False,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowSubworkflowImpactResponse:
    """分析该 workflow（子工作流）被哪些父工作流版本引用。"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    version_service = WorkflowVersionService(db)
    if target_version_id:
        version = version_service.get_version(target_version_id)
        if not version or version.workflow_id != workflow_id:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_version_not_found",
                message=MSG_VERSION_NOT_FOUND,
                details={"workflow_id": workflow_id, "version_id": target_version_id},
            )
            raise AssertionError("unreachable")
    raw = version_service.analyze_subworkflow_impact(
        target_workflow_id=workflow_id,
        target_version_id=target_version_id,
        include_only_published=published_only,
        baseline_version_id=baseline_version_id,
    )
    return WorkflowSubworkflowImpactResponse.model_validate(raw)


# 必须在 /{version_id} 之前注册，否则路径 .../versions/compare 会被当成 version_id="compare"
@router.get("/{workflow_id}/versions/compare", response_model=WorkflowVersionsCompareResponse)
async def diff_versions(
    http_request: Request,
    workflow_id: str,
    from_version_id: Annotated[str, Query(description="Base version id")],
    to_version_id: Annotated[str, Query(description="Target version id")],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowVersionsCompareResponse:
    """比较两个版本的 DAG 差异"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    version_service = WorkflowVersionService(db)
    from_version = version_service.get_version(from_version_id)
    to_version = version_service.get_version(to_version_id)

    if not from_version or from_version.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_diff_from_version_not_found",
            message="from_version not found",
            details={"workflow_id": workflow_id, "from_version_id": from_version_id},
        )
        raise AssertionError("unreachable")
    if not to_version or to_version.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_diff_to_version_not_found",
            message="to_version not found",
            details={"workflow_id": workflow_id, "to_version_id": to_version_id},
        )
        raise AssertionError("unreachable")

    from_nodes = {n.id: n for n in from_version.dag.nodes}
    to_nodes = {n.id: n for n in to_version.dag.nodes}

    from_node_ids = set(from_nodes.keys())
    to_node_ids = set(to_nodes.keys())

    added_nodes = sorted(to_node_ids - from_node_ids)
    removed_nodes = sorted(from_node_ids - to_node_ids)
    changed_nodes = sorted([
        node_id
        for node_id in (from_node_ids & to_node_ids)
        if from_nodes[node_id].model_dump(mode="json") != to_nodes[node_id].model_dump(mode="json")
    ])

    def edge_key(edge: WorkflowEdge) -> str:
        return (
            f"{edge.from_node}->{edge.to_node}"
            f"|{edge.source_handle or ''}|{edge.target_handle or ''}"
            f"|{edge.label or ''}|{edge.condition or ''}"
        )

    from_edges_map = {edge_key(e): e for e in from_version.dag.edges}
    to_edges_map = {edge_key(e): e for e in to_version.dag.edges}

    from_edge_keys = set(from_edges_map.keys())
    to_edge_keys = set(to_edges_map.keys())

    added_edges = sorted(to_edge_keys - from_edge_keys)
    removed_edges = sorted(from_edge_keys - to_edge_keys)

    return WorkflowVersionsCompareResponse(
        workflow_id=workflow_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        summary=WorkflowVersionsDiffSummaryCounts(
            node_added=len(added_nodes),
            node_removed=len(removed_nodes),
            node_changed=len(changed_nodes),
            edge_added=len(added_edges),
            edge_removed=len(removed_edges),
        ),
        nodes=WorkflowVersionsCompareNodesDiff(
            added=added_nodes,
            removed=removed_nodes,
            changed=changed_nodes,
        ),
        edges=WorkflowVersionsCompareEdgesDiff(
            added=added_edges,
            removed=removed_edges,
        ),
    )


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetailResponse)
async def get_version(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowVersionDetailResponse:
    """获取版本详情（包含 DAG）"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    version_service = WorkflowVersionService(db)
    version = version_service.get_version(version_id)

    if not version or version.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_version_not_found",
            message=MSG_VERSION_NOT_FOUND,
            details={"workflow_id": workflow_id, "version_id": version_id},
        )
        raise AssertionError("unreachable")

    return WorkflowVersionDetailResponse(
        **_version_to_response(version).model_dump(),
        dag=version.dag,
        checksum=version.checksum,
    )


@router.post("/{workflow_id}/versions/{version_id}/publish", response_model=WorkflowVersionResponse)
async def publish_version(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowVersionResponse:
    """发布版本"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "publish"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "publish"},
        )
    
    version_service = WorkflowVersionService(db)
    
    try:
        version = version_service.publish_version(version_id, current_user)
        if not version or version.workflow_id != workflow_id:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_version_not_found",
                message=MSG_VERSION_NOT_FOUND,
                details={"workflow_id": workflow_id, "version_id": version_id},
            )
            raise AssertionError("unreachable")
        return _version_to_response(version)
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_version_publish_invalid",
            message=str(e),
            details={"workflow_id": workflow_id, "version_id": version_id},
        )
        raise AssertionError("unreachable")


@router.post("/{workflow_id}/versions/{version_id}/rollback", response_model=WorkflowVersionResponse)
async def rollback_version(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    body: WorkflowVersionRollbackBody,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowVersionResponse:
    """基于历史版本创建回滚版本（可选自动发布）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "publish"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "publish"},
        )

    version_service = WorkflowVersionService(db)
    source = version_service.get_version(version_id)
    if not source or source.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_version_not_found",
            message=MSG_VERSION_NOT_FOUND,
            details={"workflow_id": workflow_id, "version_id": version_id},
        )
        raise AssertionError("unreachable")

    definition = version_service.create_definition(
        workflow_id=workflow_id,
        description=body.description or f"Rollback from version {source.version_number}",
        source_version_id=source.version_id,
        created_by=current_user,
    )

    rollback_version = version_service.create_version(
        workflow_id=workflow_id,
        definition_id=definition.definition_id,
        dag=source.dag,
        version_number=None,
        description=body.description or f"Rollback from version {source.version_number}",
        change_notes=f"rollback:{source.version_id}",
        created_by=current_user,
    )

    workflow_service.repository.update(
        workflow_id,
        {"latest_version_id": rollback_version.version_id},
        current_user,
    )

    if body.publish:
        published = version_service.publish_version(rollback_version.version_id, current_user)
        if not published:
            raise_api_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="workflow_version_rollback_publish_failed",
                message="Rollback publish failed",
                details={"workflow_id": workflow_id, "version_id": rollback_version.version_id},
            )
            raise AssertionError("unreachable")
        workflow_service.repository.update(
            workflow_id,
            {
                "published_version_id": published.version_id,
                "lifecycle_state": WorkflowLifecycleState.ACTIVE,
            },
            current_user,
        )
        return _version_to_response(published)

    return _version_to_response(rollback_version)


# ==================== Execution Endpoints ====================

def _resolve_execution_wait(wait: Optional[bool]) -> bool:
    if wait is not None:
        return wait
    return bool(getattr(settings, "workflow_execution_wait_default", False))


def _resolve_wait_timeout_seconds(wait_timeout_seconds: Optional[int]) -> int:
    default_timeout = max(1, int(getattr(settings, "workflow_wait_timeout_seconds", 120) or 120))
    max_timeout = max(default_timeout, int(getattr(settings, "workflow_wait_timeout_max_seconds", 3600) or 3600))
    requested_timeout = int(wait_timeout_seconds) if wait_timeout_seconds is not None else default_timeout
    return max(1, min(requested_timeout, max_timeout))


async def _run_execution_background(exec_id: str, *, bind: Optional[Engine] = None) -> None:
    logger.info(f"[WorkflowAPI] Background run start: execution_id={exec_id}")
    engine = bind if bind is not None else get_engine()
    db_bg: Session = sessionmaker_for_engine(engine)()
    try:
        execution_service_bg = WorkflowExecutionService(db_bg)
        exec_obj = execution_service_bg.get_execution(exec_id)
        if not exec_obj:
            logger.error(f"[WorkflowAPI] Background run skipped: execution not found {exec_id}")
            return
        # 取消/终态执行不应再启动，避免跨进程下“已取消又被启动”。
        if exec_obj.is_terminal():
            logger.info(
                f"[WorkflowAPI] Background run skipped: execution already terminal "
                f"{exec_id} state={exec_obj.state.value}"
            )
            return
        runtime_bg = WorkflowRuntime(db_bg, get_execution_manager())
        # 在后台任务里完整执行，避免 wait_for_completion=False 时 db session 过早关闭。
        final_exec = await runtime_bg.execute(exec_obj, wait_for_completion=True)
        logger.info(
            f"[WorkflowAPI] Background run finished: execution_id={exec_id} state={final_exec.state}"
        )
    except asyncio.CancelledError:
        logger.info(f"[WorkflowAPI] Background run cancelled: execution_id={exec_id}")
        try:
            runtime_bg = WorkflowRuntime(db_bg, get_execution_manager())
            await runtime_bg.cancel(exec_id)
        except Exception as e:
            logger.warning(f"[WorkflowAPI] Background cancel cleanup failed: execution_id={exec_id} error={e}")
        raise
    except Exception as e:
        logger.error(f"[WorkflowAPI] Background run failed: execution_id={exec_id} error={e}")
    finally:
        db_bg.close()


def _schedule_background_execution_task(
    execution_id: str,
    background_tasks: Optional[BackgroundTasks],
    *,
    bind: Optional[Engine] = None,
) -> None:
    # 优先直接投递事件循环，避免依赖 BackgroundTasks 触发时机导致 execution 长期停留 pending。
    try:
        task = asyncio.create_task(_run_execution_background(execution_id, bind=bind))
        _WORKFLOW_BG_TASKS.add(task)
        _WORKFLOW_BG_TASK_BY_EXECUTION[execution_id] = task

        def _on_done(t: asyncio.Task, exec_id: str = execution_id) -> None:
            _WORKFLOW_BG_TASKS.discard(t)
            if _WORKFLOW_BG_TASK_BY_EXECUTION.get(exec_id) is t:
                _WORKFLOW_BG_TASK_BY_EXECUTION.pop(exec_id, None)

        task.add_done_callback(_on_done)
    except RuntimeError:
        # 兜底：无 running loop 时退回 Starlette BackgroundTasks。
        if background_tasks is None:
            raise
        background_tasks.add_task(_run_execution_background, execution_id, bind=bind)


async def _resolve_idempotent_execution_hit(
    *,
    claim: Any,
    execution_service: WorkflowExecutionService,
    workflow_id: str,
    tenant_id: str,
) -> WorkflowExecutionResponse:
    if claim.record.response_ref:
        ex = execution_service.get_execution(claim.record.response_ref, tenant_id=tenant_id)
        if ex:
            logger.info(
                f"[WorkflowAPI] Idempotent create hit: workflow_id={workflow_id} "
                f"execution_id={ex.execution_id}"
            )
            ex = await _hydrate_execution_live_from_kernel(ex)
            node_timeline_override = None
            if ex.graph_instance_id:
                node_timeline_override = await _node_timeline_from_event_store(ex.graph_instance_id)
            return _execution_to_response(ex, node_timeline_override=node_timeline_override)
    raise_api_error(
        status_code=status.HTTP_409_CONFLICT,
        code="idempotency_in_progress",
        message="Idempotent request is still processing; retry later",
        details={"scope": "workflow_execution_create"},
    )
    raise AssertionError("unreachable")


def _validate_execution_create_access(
    *,
    db: Session,
    http_request: Request,
    workflow_id: str,
    request: WorkflowExecutionCreateRequest,
    current_user: str,
) -> None:
    tenant_id = resolve_api_tenant_id(http_request)
    if request.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_id_mismatch",
            message=f"workflow_id mismatch: path={workflow_id} body={request.workflow_id}",
        )
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "execute"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "execute"},
        )


async def _prepare_execution_create_idempotency(
    *,
    db: Session,
    http_request: Request,
    workflow_id: str,
    request: WorkflowExecutionCreateRequest,
    current_user: str,
    execution_service: WorkflowExecutionService,
) -> tuple[Optional[str], IdempotencyService, Optional[Any], Optional[WorkflowExecutionResponse]]:
    idem_key = _extract_idempotency_key(http_request) if http_request else None
    idem_service = IdempotencyService(db)
    idem_record: Optional[Any] = None
    hit_response: Optional[WorkflowExecutionResponse] = None

    if not idem_key:
        return idem_key, idem_service, idem_record, hit_response

    tenant_id = resolve_api_tenant_id(http_request)
    req_hash = _stable_request_hash(
        {
            "workflow_id": workflow_id,
            "version_id": request.version_id,
            "input_data": request.input_data,
            "global_context": request.global_context,
            "trigger_type": request.trigger_type,
        }
    )
    claim = idem_service.claim(
        scope="workflow_execution_create",
        owner_id=str(current_user or "default"),
        key=idem_key,
        request_hash=req_hash,
        tenant_id=tenant_id,
    )
    if claim.conflict:
        raise_api_error(
            status_code=status.HTTP_409_CONFLICT,
            code="idempotency_conflict",
            message="Idempotency-Key already used with different request payload",
            details={"scope": "workflow_execution_create"},
        )
    idem_record = claim.record
    if not claim.is_new:
        hit_response = await _resolve_idempotent_execution_hit(
            claim=claim,
            execution_service=execution_service,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )
    return idem_key, idem_service, idem_record, hit_response


def _create_execution_record(
    *,
    request: WorkflowExecutionCreateRequest,
    execution_service: WorkflowExecutionService,
    current_user: str,
    idem_key: Optional[str],
    idem_service: IdempotencyService,
    idem_record: Optional[Any],
) -> WorkflowExecution:
    try:
        global_ctx = dict(request.global_context or {})
        if idem_key:
            global_ctx["__idempotency_key"] = idem_key
        create_req = WorkflowExecutionCreateRequest(
            workflow_id=request.workflow_id,
            version_id=request.version_id,
            input_data=request.input_data,
            global_context=global_ctx,
            trigger_type=request.trigger_type,
        )
        execution = execution_service.create_execution(create_req, current_user)
        if idem_record:
            idem_service.mark_succeeded(record_id=idem_record.id, response_ref=execution.execution_id)
        return execution
    except ValueError as e:
        if idem_record:
            idem_service.mark_failed(record_id=idem_record.id, error_message=str(e))
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_execution_invalid_request",
            message=str(e),
        )
        raise AssertionError("unreachable")


@router.post("/{workflow_id}/executions", response_model=WorkflowExecutionResponse, status_code=status.HTTP_201_CREATED)
async def create_execution(
    http_request: Request,
    workflow_id: str,
    request: WorkflowExecutionCreateRequest,
    background_tasks: BackgroundTasks,
    wait: Annotated[Optional[bool], Query(description="Wait for completion")] = None,
    wait_timeout_seconds: Annotated[Optional[int], Query(
        ge=1,
        description="wait=true 时的同步等待超时（秒）",
    )] = None,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionResponse:
    """创建并执行工作流"""
    _validate_execution_create_access(
        db=db,
        http_request=http_request,
        workflow_id=workflow_id,
        request=request,
        current_user=current_user,
    )
    execution_service = WorkflowExecutionService(db)
    idem_key, idem_service, idem_record, hit_response = await _prepare_execution_create_idempotency(
        db=db,
        http_request=http_request,
        workflow_id=workflow_id,
        request=request,
        current_user=current_user,
        execution_service=execution_service,
    )
    if hit_response is not None:
        return hit_response
    execution = _create_execution_record(
        request=request,
        execution_service=execution_service,
        current_user=current_user,
        idem_key=idem_key,
        idem_service=idem_service,
        idem_record=idem_record,
    )
    
    effective_wait = _resolve_execution_wait(wait)

    # 执行
    if effective_wait:
        execution_manager = get_execution_manager()
        runtime = WorkflowRuntime(db, execution_manager)
        effective_wait_timeout = _resolve_wait_timeout_seconds(wait_timeout_seconds)
        
        try:
            execution = await runtime.execute(
                execution,
                wait_for_completion=True,
                wait_timeout_seconds=effective_wait_timeout,
            )
        except Exception as e:
            raise_api_error(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="workflow_runtime_error",
                message=str(e),
                details={"workflow_id": workflow_id, "execution_id": execution.execution_id},
            )
    else:
        _schedule_background_execution_task(
            execution_id=execution.execution_id,
            background_tasks=background_tasks,
            bind=db.get_bind(),
        )
    
    return _execution_to_response(execution)


@router.get("/{workflow_id}/executions", response_model=WorkflowExecutionListEnvelope)
async def list_executions(
    http_request: Request,
    workflow_id: str,
    state: Optional[WorkflowExecutionState] = None,
    limit: Annotated[int, Query(le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    live: Annotated[bool, Query(description="实时对齐执行状态（从内核视图回填）")] = True,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionListEnvelope:
    """列出执行记录"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    
    execution_service = WorkflowExecutionService(db)
    executions = execution_service.list_executions(
        workflow_id=workflow_id,
        state=state,
        limit=limit,
        offset=offset,
        tenant_id=tenant_id,
    )
    total = execution_service.count_executions(
        workflow_id=workflow_id,
        state=state,
        tenant_id=tenant_id,
    )

    if live and executions:
        hydrated = []
        for e in executions:
            item = e
            try:
                if e.state in {WorkflowExecutionState.PENDING, WorkflowExecutionState.RUNNING}:
                    item = await _hydrate_execution_live_from_kernel(e)
                    item = _maybe_persist_terminal_reconcile(execution_service, item)
            except Exception as ex:
                logger.debug(
                    f"[WorkflowAPI] list live hydrate skipped: execution_id={e.execution_id} err={ex}"
                )
            hydrated.append(item)
        executions = hydrated
    
    return WorkflowExecutionListEnvelope(
        items=[_execution_to_response(e) for e in executions],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{workflow_id}/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_execution(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    reconcile: Annotated[bool, Query(description="Force terminal reconcile write-back")] = False,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionResponse:
    """获取执行详情"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    
    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    execution = await _hydrate_execution_live_from_kernel(execution)
    if reconcile:
        execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_response(execution, node_timeline_override=node_timeline_override)


@router.get("/{workflow_id}/executions/{execution_id}/errors", response_model=WorkflowExecutionErrorLogsListEnvelope)
async def list_execution_errors(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    node_id: Optional[str] = None,
    error_type: Optional[str] = None,
    failure_strategy: Optional[str] = None,
    start_time: Optional[str] = Query(default=None, description="ISO8601 start time"),
    end_time: Optional[str] = Query(default=None, description="ISO8601 end time"),
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowExecutionErrorLogsListEnvelope:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    execution = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")
    if not execution.graph_instance_id:
        return WorkflowExecutionErrorLogsListEnvelope(items=[], total=0, limit=limit, offset=offset)
    start_dt = _parse_query_iso_datetime(start_time)
    end_dt = _parse_query_iso_datetime(end_time)
    if start_time and start_dt is None:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_start_time",
            message="start_time must be valid ISO8601 datetime",
            details={"start_time": start_time},
        )
    if end_time and end_dt is None:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_end_time",
            message="end_time must be valid ISO8601 datetime",
            details={"end_time": end_time},
        )
    if start_dt and end_dt and start_dt > end_dt:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_time_range",
            message="start_time must be earlier than or equal to end_time",
            details={"start_time": start_time, "end_time": end_time},
        )
    rows = await _execution_error_logs_from_event_store(
        instance_id=execution.graph_instance_id,
        execution_id=execution.execution_id,
        node_id=node_id,
        error_type=error_type,
        failure_strategy=failure_strategy,
        start_dt=start_dt,
        end_dt=end_dt,
    )
    total = len(rows)
    sliced = rows[offset : offset + limit]
    parsed = [WorkflowExecutionErrorLogRow.model_validate(r) for r in sliced]
    return WorkflowExecutionErrorLogsListEnvelope(items=parsed, total=total, limit=limit, offset=offset)


@router.get("/{workflow_id}/executions/{execution_id}/failure-report", response_model=WorkflowExecutionFailureReportResponse)
async def get_execution_failure_report(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    node_id: Optional[str] = None,
    error_type: Optional[str] = None,
    failure_strategy: Optional[str] = None,
    start_time: Optional[str] = Query(default=None, description="ISO8601 start time"),
    end_time: Optional[str] = Query(default=None, description="ISO8601 end time"),
    redact_sensitive: Annotated[bool, Query(description="Redact sensitive fields in report payload")] = True,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowExecutionFailureReportResponse:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    execution = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    start_dt = _parse_query_iso_datetime(start_time)
    end_dt = _parse_query_iso_datetime(end_time)
    if start_time and start_dt is None:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_start_time",
            message="start_time must be valid ISO8601 datetime",
            details={"start_time": start_time},
        )
    if end_time and end_dt is None:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_end_time",
            message="end_time must be valid ISO8601 datetime",
            details={"end_time": end_time},
        )
    if start_dt and end_dt and start_dt > end_dt:
        raise_api_error(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="workflow_invalid_time_range",
            message="start_time must be earlier than or equal to end_time",
            details={"start_time": start_time, "end_time": end_time},
        )

    execution = await _hydrate_execution_live_from_kernel(execution)
    node_timeline_override: Optional[List[Dict[str, Any]]] = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)

    execution_payload = _execution_to_response(
        execution,
        node_timeline_override=node_timeline_override,
    ).model_dump()
    error_rows: List[Dict[str, Any]] = []
    if execution.graph_instance_id:
        error_rows = await _execution_error_logs_from_event_store(
            instance_id=execution.graph_instance_id,
            execution_id=execution.execution_id,
            node_id=node_id,
            error_type=error_type,
            failure_strategy=failure_strategy,
            start_dt=start_dt,
            end_dt=end_dt,
        )

    report = _build_failure_report_payload(
        workflow_id=workflow_id,
        execution=execution,
        execution_payload=execution_payload,
        error_rows=error_rows,
        selected_node_id=node_id,
        error_type=error_type,
        failure_strategy=failure_strategy,
        start_time=start_time,
        end_time=end_time,
    )
    if redact_sensitive:
        redacted_report, redacted_count = _redact_sensitive_value_with_count(report)
        if isinstance(redacted_report, dict):
            redacted_report["redaction_applied"] = True
            redacted_report["redacted_key_count"] = redacted_count
            redacted_report["report_sha256"] = _compute_report_sha256(redacted_report)
        return WorkflowExecutionFailureReportResponse.model_validate(cast(Dict[str, Any], redacted_report))
    report["redaction_applied"] = False
    report["redacted_key_count"] = 0
    report["report_sha256"] = _compute_report_sha256(report)
    return WorkflowExecutionFailureReportResponse.model_validate(report)


@router.get("/{workflow_id}/executions/{execution_id}/failure-report/archive")
async def download_execution_failure_report_archive(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    node_id: Optional[str] = None,
    error_type: Optional[str] = None,
    failure_strategy: Optional[str] = None,
    start_time: Optional[str] = Query(default=None, description="ISO8601 start time"),
    end_time: Optional[str] = Query(default=None, description="ISO8601 end time"),
    redact_sensitive: Annotated[bool, Query(description="Redact sensitive fields in archive payload")] = True,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Response:
    report_model = await get_execution_failure_report(
        http_request=http_request,
        workflow_id=workflow_id,
        execution_id=execution_id,
        node_id=node_id,
        error_type=error_type,
        failure_strategy=failure_strategy,
        start_time=start_time,
        end_time=end_time,
        redact_sensitive=redact_sensitive,
        db=db,
        current_user=current_user,
    )
    report = report_model.model_dump(mode="json")
    events: List[Dict[str, Any]] = []
    graph_instance_id = report.get("execution", {}).get("graph_instance_id")
    if isinstance(graph_instance_id, str) and graph_instance_id.strip():
        events = await _execution_events_from_event_store(graph_instance_id)
    if redact_sensitive:
        redacted_events, events_redacted_count = _redact_sensitive_value_with_count(events)
        events = cast(List[Dict[str, Any]], redacted_events)
        report["redacted_key_count"] = int(report.get("redacted_key_count") or 0) + int(events_redacted_count)
    archive_bytes = _build_failure_report_archive_bytes(report=report, events=events)
    filename = f"workflow-failure-bundle-{execution_id}.zip"
    schema_version = str(report.get("report_schema_version") or "")
    redaction_applied = "true" if bool(report.get("redaction_applied")) else "false"
    redacted_key_count = str(int(report.get("redacted_key_count") or 0))
    report_sha256 = str(report.get("report_sha256") or "")
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Schema-Version": schema_version,
            "X-Redaction-Applied": redaction_applied,
            "X-Redacted-Key-Count": redacted_key_count,
            "X-Report-Sha256": report_sha256,
        },
    )


@router.get("/{workflow_id}/executions/{execution_id}/call-chain", response_model=WorkflowExecutionCallChainResponse)
async def get_execution_call_chain(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowExecutionCallChainResponse:
    """查询执行调用链（父子工作流）。"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
        raise AssertionError("unreachable")
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution_service = WorkflowExecutionService(db)
    root_execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not root_execution or root_execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    candidate_executions = execution_service.list_executions(
        workflow_id=None,
        state=None,
        limit=limit,
        offset=0,
        tenant_id=tenant_id,
    )
    correlation_id, chain_items = _build_execution_call_chain(root_execution, candidate_executions)
    return WorkflowExecutionCallChainResponse(
        root_execution_id=root_execution.execution_id,
        correlation_id=correlation_id,
        items=chain_items,
        total=len(chain_items),
    )


async def _kernel_debug_snapshot(graph_instance_id: str) -> Dict[str, Any]:
    try:
        kernel_db = Database()
        return await GraphRuntimeAdapter.extract_execution_result_from_kernel(
            graph_instance_id,
            kernel_db,
        )
    except Exception as e:
        return {"_error": str(e)}


async def _recent_events_debug(instance_id: Optional[str], limit: int = 80) -> Any:
    if not instance_id:
        return []
    try:
        kernel_db = Database()
        async with kernel_db.async_session() as session:
            store = EventStore(session)
            events = await store.get_latest_events(instance_id, limit=limit)
        out: List[Dict[str, Any]] = []
        for ev in reversed(events):
            et = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)
            out.append(
                {
                    "event_id": ev.event_id,
                    "sequence": ev.sequence,
                    "event_type": et,
                    "timestamp": ev.timestamp,
                    "payload": ev.payload,
                }
            )
        return out
    except Exception as e:
        return [{"_error": str(e)}]


@router.get("/{workflow_id}/executions/{execution_id}/debug", response_model=WorkflowExecutionDebugResponse)
async def get_execution_debug(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    event_limit: Annotated[int, Query(ge=1, le=500)] = 80,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowExecutionDebugResponse:
    """
    工作流调试视图：聚合 hydrated 执行详情、内核快照与 execution_kernel 近期事件。
    需对工作流具有 read 权限。
    """
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    execution = await _hydrate_execution_live_from_kernel(execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)

    kernel_snapshot = None
    if execution.graph_instance_id:
        kernel_snapshot = await _kernel_debug_snapshot_helper(execution.graph_instance_id)

    recent_events = await _recent_events_debug_helper(execution.graph_instance_id, limit=event_limit)

    return WorkflowExecutionDebugResponse(
        execution=_execution_to_response(
            execution, node_timeline_override=node_timeline_override
        ),
        kernel_snapshot=_as_optional_workflow_json_map(kernel_snapshot)
        if isinstance(kernel_snapshot, dict)
        else None,
        recent_events=_as_workflow_json_records(recent_events if isinstance(recent_events, list) else []),
        debug=WorkflowExecutionDebugBundle(
            graph_instance_id=execution.graph_instance_id,
            replay_hint=execution.graph_instance_id or execution.execution_id,
        ),
    )


@router.delete("/{workflow_id}/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Response:
    """删除单个执行历史（仅允许终态）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "admin"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_admin_required",
            message=MSG_ADMIN_ACCESS_REQUIRED,
            details={"workflow_id": workflow_id, "action": "admin"},
        )

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")
    try:
        deleted = execution_service.delete_execution(execution_id, tenant_id=tenant_id)
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_409_CONFLICT,
            code="workflow_execution_delete_conflict",
            message=str(e),
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    if not deleted:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workflow_id}/executions/{execution_id}/status", response_model=WorkflowExecutionStatusResponse)
async def get_execution_status(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionStatusResponse:
    """获取轻量执行状态（用于运行页高频轮询）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    execution = await _hydrate_execution_live_from_kernel(execution)
    execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_status_response(execution, node_timeline_override=node_timeline_override)


def _sse_data(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_workflow_status_delta(status_payload: Dict[str, Any]) -> Dict[str, Any]:
    """压缩执行状态事件，降低 SSE 负载。"""
    return {
        "schema_version": SSE_STATUS_DELTA_SCHEMA_VERSION,
        "execution_id": status_payload.get("execution_id"),
        "workflow_id": status_payload.get("workflow_id"),
        "version_id": status_payload.get("version_id"),
        "state": status_payload.get("state"),
        "started_at": status_payload.get("started_at"),
        "finished_at": status_payload.get("finished_at"),
        "duration_ms": status_payload.get("duration_ms"),
        "queue_position": status_payload.get("queue_position"),
        "wait_duration_ms": status_payload.get("wait_duration_ms"),
        "node_timeline_count": len(status_payload.get("node_timeline") or []),
    }


async def _load_execution_status_payload(
    *,
    execution_id: str,
    workflow_id: str,
    loop_exec_svc: WorkflowExecutionService,
    tenant_id: str,
) -> tuple[Optional[Dict[str, Any]], Optional[bool], Optional[str]]:
    current = loop_exec_svc.get_execution(execution_id, tenant_id=tenant_id)
    if not current or current.workflow_id != workflow_id:
        return None, None, MSG_EXECUTION_NOT_FOUND

    current = await _hydrate_execution_live_from_kernel(current)
    current = _maybe_persist_terminal_reconcile(loop_exec_svc, current)
    timeline_override = None
    if current.graph_instance_id:
        timeline_override = await _node_timeline_from_event_store(current.graph_instance_id)
    status_payload = _execution_to_status_response(
        current,
        node_timeline_override=timeline_override,
    ).model_dump(mode="json")
    return status_payload, current.is_terminal(), None


def _build_status_or_heartbeat_event(
    *,
    current_hash: str,
    last_hash: Optional[str],
    heartbeat_at: datetime,
    now: datetime,
    heartbeat_every: int,
    status_payload: Dict[str, Any],
    compact: bool = False,
) -> tuple[Optional[str], Optional[str], datetime]:
    if current_hash != last_hash:
        if compact:
            event = _sse_data({"type": "status_delta", "payload": _build_workflow_status_delta(status_payload)})
        else:
            event = _sse_data({"type": "status", "payload": status_payload})
        return event, current_hash, now

    if (now - heartbeat_at).total_seconds() >= heartbeat_every:
        event = _sse_data({"type": "heartbeat", "at": now.isoformat()})
        return event, current_hash, now

    return None, last_hash, heartbeat_at


def _validate_stream_access(
    *,
    init_db: Session,
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    current_user: str,
) -> None:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(init_db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution_service = WorkflowExecutionService(init_db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )


async def _stream_status_tick(
    *,
    db: Session,
    workflow_id: str,
    execution_id: str,
    tenant_id: str,
    last_hash: Optional[str],
    heartbeat_at: datetime,
    heartbeat_every: int,
    compact: bool = False,
    sse_accept_language: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], datetime, bool]:
    # 每轮独立 Session 以便读到最新执行状态；bind 与 Depends(get_db) 一致（测试 override 同引擎）
    loop_db = sessionmaker_for_engine(db.get_bind())()
    try:
        loop_exec_svc = WorkflowExecutionService(loop_db)
        status_payload, is_terminal, error_message = await _load_execution_status_payload(
            execution_id=execution_id,
            workflow_id=workflow_id,
            loop_exec_svc=loop_exec_svc,
            tenant_id=tenant_id,
        )
        if error_message:
            msg_out = error_message
            if error_message == MSG_EXECUTION_NOT_FOUND:
                msg_out = localize_error_message(
                    code="workflow_execution_not_found",
                    default_message=MSG_EXECUTION_NOT_FOUND,
                    accept_language=sse_accept_language,
                )
            return (
                _sse_data(
                    {
                        "type": "error",
                        "error_code": SSE_STREAM_RESOURCE_NOT_FOUND_ERROR_CODE,
                        "message": msg_out,
                    }
                ),
                last_hash,
                heartbeat_at,
                True,
            )
        if status_payload is None or is_terminal is None:
            msg_nf = localize_error_message(
                code="workflow_execution_not_found",
                default_message=MSG_EXECUTION_NOT_FOUND,
                accept_language=sse_accept_language,
            )
            return (
                _sse_data(
                    {
                        "type": "error",
                        "error_code": SSE_STREAM_RESOURCE_NOT_FOUND_ERROR_CODE,
                        "message": msg_nf,
                    }
                ),
                last_hash,
                heartbeat_at,
                True,
            )

        current_hash = json.dumps(status_payload, ensure_ascii=False, sort_keys=True)
        now = datetime.now(UTC)
        event, next_hash, next_heartbeat_at = _build_status_or_heartbeat_event(
            current_hash=current_hash,
            last_hash=last_hash,
            heartbeat_at=heartbeat_at,
            now=now,
            heartbeat_every=heartbeat_every,
            status_payload=status_payload,
            compact=compact,
        )
        if is_terminal:
            terminal_event = _sse_data({"type": "terminal", "state": status_payload.get("state")})
            # 保持原语义：终态时本轮先发 status/heartbeat（若有），再发 terminal。
            combined_event = f"{event}{terminal_event}" if event is not None else terminal_event
            return combined_event, (next_hash or last_hash), next_heartbeat_at, True
        return event, (next_hash or last_hash), next_heartbeat_at, False
    finally:
        loop_db.close()


@router.get("/{workflow_id}/executions/{execution_id}/stream")
async def stream_execution_status(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    interval_ms: Annotated[int, Query(ge=300, le=5000, description="SSE 推送间隔（毫秒）")] = 900,
    compact: Annotated[bool, Query(description="true 时推送 status_delta（轻量增量）")] = False,
    lang: Annotated[
        Optional[str],
        Query(description="UI locale for SSE payloads (zh|en); EventSource cannot set Accept-Language"),
    ] = None,
    *,
    current_user: Annotated[str, Depends(get_current_user)],
) -> StreamingResponse:
    """SSE 推送执行状态（节点级），前端可替代高频轮询；轮询仍可作为降级路径。"""
    accept_sse = resolve_accept_language_for_sse(http_request, lang)
    stream_tenant_id = resolve_api_tenant_id(http_request)
    _validate_stream_access(
        init_db=db,
        http_request=http_request,
        workflow_id=workflow_id,
        execution_id=execution_id,
        current_user=current_user,
    )

    async def _event_stream() -> AsyncIterator[str]:
        last_hash: Optional[str] = None
        heartbeat_every = 15
        heartbeat_at = datetime.now(UTC)
        sleep_s = max(0.3, interval_ms / 1000.0)

        while True:
            try:
                event, last_hash, heartbeat_at, should_stop = await _stream_status_tick(
                    db=db,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    tenant_id=stream_tenant_id,
                    last_hash=last_hash,
                    heartbeat_at=heartbeat_at,
                    heartbeat_every=heartbeat_every,
                    compact=compact,
                    sse_accept_language=accept_sse,
                )
                if event is not None:
                    yield event
                if should_stop:
                    break

                await asyncio.sleep(sleep_s)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(
                    f"[WorkflowAPI] status stream loop error: execution_id={execution_id} err={e}"
                )
                yield _sse_data(
                    {
                        "type": "error",
                        "error_code": SSE_STREAM_RUNTIME_ERROR_CODE,
                        "message": str(e),
                    }
                )
                await asyncio.sleep(min(2.0, sleep_s))

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{workflow_id}/executions/{execution_id}/cancel", response_model=WorkflowExecutionResponse)
async def cancel_execution(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionResponse:
    """取消执行"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "execute"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "execute"},
        )
    
    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    # 幂等取消：对已终态执行直接返回当前状态，不视为错误。
    if execution.is_terminal():
        return _execution_to_response(execution)
    
    try:
        # 优先取消 API 层后台任务，避免其持续占用等待链路。
        bg_task = _WORKFLOW_BG_TASK_BY_EXECUTION.get(execution_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()
        _WORKFLOW_BG_TASK_BY_EXECUTION.pop(execution_id, None)
        runtime = WorkflowRuntime(db, get_execution_manager())
        ok = await runtime.cancel(execution_id)
        if not ok:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_execution_not_found",
                message=MSG_EXECUTION_NOT_FOUND,
                details={"workflow_id": workflow_id, "execution_id": execution_id},
            )
            raise AssertionError("unreachable")
        execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
        if not execution or execution.workflow_id != workflow_id:
            raise_api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="workflow_execution_not_found",
                message=MSG_EXECUTION_NOT_FOUND,
                details={"workflow_id": workflow_id, "execution_id": execution_id},
            )
            raise AssertionError("unreachable")
        return _execution_to_response(execution)
    except ValueError as e:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_cancel_invalid_request",
            message=str(e),
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")


@router.post("/{workflow_id}/executions/{execution_id}/reconcile", response_model=WorkflowExecutionResponse)
async def reconcile_execution(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowExecutionResponse:
    """手动触发终态对账，用于异常场景恢复（如节点已终态但 execution 仍显示 running）。"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution_service = WorkflowExecutionService(db)
    execution = execution_service.get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")

    execution = await _hydrate_execution_live_from_kernel(execution)
    execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_response(execution, node_timeline_override=node_timeline_override)


@router.get(
    "/{workflow_id}/executions/{execution_id}/approvals",
    response_model=Union[WorkflowApprovalListResponse, List[WorkflowApprovalTaskResponse]],
)
async def list_execution_approvals(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    response: Response,
    legacy: Annotated[bool, Query(description="Return legacy array response format")] = False,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Any:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    execution = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    items = [_approval_task_to_response(x) for x in service.list_for_execution(execution_id, tenant_id=tenant_id)]
    if legacy:
        if response is not None:
            response.headers["X-API-Deprecated"] = str(
                getattr(settings, "workflow_approvals_legacy_deprecated_header", "approvals-legacy-format")
            )
            response.headers["Sunset"] = str(
                getattr(settings, "workflow_approvals_legacy_sunset", "Wed, 31 Dec 2026 23:59:59 GMT")
            )
        return items
    return WorkflowApprovalListResponse(
        execution_id=execution_id,
        execution_state=execution.state.value if execution else None,
        items=items,
    )


@router.post(
    "/{workflow_id}/executions/{execution_id}/approvals/{task_id}/approve",
    response_model=WorkflowApprovalTaskResponse,
)
async def approve_execution_approval(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowApprovalTaskResponse:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "execute"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "execute"},
        )

    execution = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    decision = service.approve(
        execution_id=execution_id, task_id=task_id, decided_by=current_user, tenant_id=tenant_id
    )
    if not decision.task:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_approval_task_not_found",
            message="Approval task not found",
            details={"task_id": task_id, "execution_id": execution_id},
        )
    if decision.expired:
        raise_api_error(
            status_code=409,
            code="workflow_approval_task_expired",
            message="Approval task expired",
            details={"task_id": task_id, "execution_id": execution_id},
        )
    execution_after = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    execution_state = execution_after.state.value if execution_after else None
    return _approval_task_to_response(decision.task, execution_state_after_decision=execution_state)


@router.post(
    "/{workflow_id}/executions/{execution_id}/approvals/{task_id}/reject",
    response_model=WorkflowApprovalTaskResponse,
)
async def reject_execution_approval(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowApprovalTaskResponse:
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "execute"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "execute"},
        )

    execution = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    decision = service.reject(
        execution_id=execution_id, task_id=task_id, decided_by=current_user, tenant_id=tenant_id
    )
    if not decision.task:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_approval_task_not_found",
            message="Approval task not found",
            details={"task_id": task_id, "execution_id": execution_id},
        )
    if decision.expired:
        raise_api_error(
            status_code=409,
            code="workflow_approval_task_expired",
            message="Approval task expired",
            details={"task_id": task_id, "execution_id": execution_id},
        )
    execution_after = WorkflowExecutionService(db).get_execution(execution_id, tenant_id=tenant_id)
    execution_state = execution_after.state.value if execution_after else None
    return _approval_task_to_response(decision.task, execution_state_after_decision=execution_state)


# ==================== Quota Endpoints ====================

@router.get("/{workflow_id}/quota", response_model=WorkflowGovernanceStatusResponse)
async def get_quota_status(
    http_request: Request,
    workflow_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowGovernanceStatusResponse:
    """获取配额状态"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    
    execution_manager = get_execution_manager()
    return WorkflowGovernanceStatusResponse.model_validate(execution_manager.get_workflow_status(workflow_id))


@router.put("/{workflow_id}/quota", response_model=WorkflowGovernanceStatusResponse)
async def set_quota(
    http_request: Request,
    workflow_id: str,
    config: QuotaConfig,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowGovernanceStatusResponse:
    """设置配额"""
    tenant_id = resolve_api_tenant_id(http_request)
    # 检查权限
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "admin"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_admin_required",
            message=MSG_ADMIN_ACCESS_REQUIRED,
            details={"workflow_id": workflow_id, "action": "admin"},
        )
    
    execution_manager = get_execution_manager()
    execution_manager.set_quota(workflow_id, config)

    return WorkflowGovernanceStatusResponse.model_validate(execution_manager.get_workflow_status(workflow_id))


@router.get("/{workflow_id}/governance", response_model=WorkflowGovernanceStatusResponse)
async def get_governance_config(
    http_request: Request,
    workflow_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowGovernanceStatusResponse:
    """获取 workflow 执行治理参数与状态（队列/背压/并发）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )
    execution_manager = get_execution_manager()
    return WorkflowGovernanceStatusResponse.model_validate(execution_manager.get_workflow_status(workflow_id))


@router.put("/{workflow_id}/governance", response_model=WorkflowGovernanceStatusResponse)
async def set_governance_config(
    http_request: Request,
    workflow_id: str,
    config: WorkflowGovernanceConfigRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowGovernanceStatusResponse:
    """设置 workflow 执行治理参数（队列/背压）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "admin"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_admin_required",
            message=MSG_ADMIN_ACCESS_REQUIRED,
            details={"workflow_id": workflow_id, "action": "admin"},
        )
    if config.backpressure_strategy and config.backpressure_strategy not in {"wait", "reject"}:
        raise_api_error(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="workflow_governance_invalid_backpressure_strategy",
            message="backpressure_strategy must be wait or reject",
        )

    execution_manager = get_execution_manager()
    old_status = execution_manager.get_workflow_status(workflow_id)
    old_queue_cfg = dict((old_status.get("queue") or {}))
    execution_manager.set_workflow_governance_config(
        workflow_id,
        max_queue_size=config.max_queue_size,
        backpressure_strategy=config.backpressure_strategy,
    )
    new_status = execution_manager.get_workflow_status(workflow_id)
    new_queue_cfg = dict((new_status.get("queue") or {}))

    audit_repo = WorkflowGovernanceAuditRepository(db)
    audit_repo.create_audit(
        workflow_id=workflow_id,
        changed_by=current_user,
        old_config={
            "max_queue_size": old_queue_cfg.get("max_queue_size"),
            "backpressure_strategy": old_queue_cfg.get("backpressure_strategy"),
        },
        new_config={
            "max_queue_size": new_queue_cfg.get("max_queue_size"),
            "backpressure_strategy": new_queue_cfg.get("backpressure_strategy"),
        },
        tenant_id=tenant_id,
    )
    return WorkflowGovernanceStatusResponse.model_validate(new_status)


@router.get("/{workflow_id}/governance/audits", response_model=WorkflowGovernanceAuditListEnvelope)
async def list_governance_audits(
    http_request: Request,
    workflow_id: str,
    limit: Annotated[int, Query(le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> WorkflowGovernanceAuditListEnvelope:
    """获取 workflow 治理配置变更审计记录"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    audit_repo = WorkflowGovernanceAuditRepository(db)
    raw_items = audit_repo.list_audits(workflow_id, limit=limit, offset=offset, tenant_id=tenant_id)
    total = audit_repo.count_audits(workflow_id, tenant_id=tenant_id)
    items = [WorkflowGovernanceAuditEntry.model_validate(x) for x in raw_items]
    return WorkflowGovernanceAuditListEnvelope(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/{workflow_id}/tool-composition/usage",
    response_model=ToolCompositionUsageRecordedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_tool_composition_usage(
    http_request: Request,
    workflow_id: str,
    request: ToolCompositionUsageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> ToolCompositionUsageRecordedResponse:
    """记录工具组合使用行为（用于推荐学习）"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    recommender = WorkflowToolCompositionRecommender()
    recommender.record_usage(
        workflow_id=workflow_id,
        user_id=current_user,
        template_id=request.template_id.strip(),
        tool_sequence=request.tool_sequence or [],
    )
    return ToolCompositionUsageRecordedResponse(ok=True)


@router.get(
    "/{workflow_id}/tool-composition/templates/recommend",
    response_model=ToolCompositionRecommendResponse,
)
async def recommend_tool_composition_templates(
    http_request: Request,
    workflow_id: str,
    current_tools: Annotated[str, Query(description="comma separated tool names")] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> ToolCompositionRecommendResponse:
    """返回工具组合模板推荐"""
    tenant_id = resolve_api_tenant_id(http_request)
    workflow_service = WorkflowService(db)
    workflow = workflow_service.get_workflow(workflow_id, tenant_id=tenant_id)
    if not workflow:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_not_found",
            message=MSG_WORKFLOW_NOT_FOUND,
            details={"workflow_id": workflow_id},
        )
    workflow = _ensure_workflow_tenant(workflow, tenant_id)
    if not workflow.has_permission(current_user, "read"):
        raise_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="workflow_access_denied",
            message=MSG_ACCESS_DENIED,
            details={"workflow_id": workflow_id, "action": "read"},
        )

    tools = [x.strip() for x in (current_tools or "").split(",") if x.strip()]
    recommender = WorkflowToolCompositionRecommender()
    items = recommender.recommend(
        workflow_id=workflow_id,
        user_id=current_user,
        current_tools=tools,
        limit=limit,
    )
    parsed = [ToolCompositionRecommendItem.model_validate(x) for x in items]
    return ToolCompositionRecommendResponse(items=parsed, total=len(parsed))


# ==================== Helper Functions ====================

def _workflow_to_response(workflow: Workflow) -> WorkflowResponse:
    """转换 Workflow 为响应格式"""
    return WorkflowResponse(
        id=workflow.id,
        namespace=workflow.namespace,
        name=workflow.name,
        description=workflow.description,
        lifecycle_state=workflow.lifecycle_state.value,
        latest_version_id=workflow.latest_version_id,
        published_version_id=workflow.published_version_id,
        owner_id=workflow.owner_id,
        tags=workflow.tags,
        created_at=workflow.created_at.isoformat() if workflow.created_at else "",
        updated_at=workflow.updated_at.isoformat() if workflow.updated_at else ""
    )


def _version_to_response(version: WorkflowVersion) -> WorkflowVersionResponse:
    """转换 WorkflowVersion 为响应格式"""
    return WorkflowVersionResponse(
        version_id=version.version_id,
        workflow_id=version.workflow_id,
        version_number=version.version_number,
        state=version.state.value,
        description=version.description,
        created_by=version.created_by,
        published_by=version.published_by,
        created_at=version.created_at.isoformat() if version.created_at else "",
        published_at=version.published_at.isoformat() if version.published_at else None
    )


_TERMINAL_TIMELINE_STATES = {"success", "failed", "skipped", "timeout", "cancelled"}


def _timeline_ts_to_iso(ts_ms: int) -> str:
    try:
        return datetime.fromtimestamp(ts_ms / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except Exception:
        return ""


def _event_node_id(payload: Any) -> str:
    return (payload or {}).get("node_id") or ""


def _ensure_timeline_node(
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    node_id: str,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    row = by_node.setdefault(
        node_id,
        {
            "node_id": node_id,
            "state": state or "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "retry_count": retry_counts.get(node_id, 0),
            "error_message": None,
            "error_type": None,
            "error_stack": None,
            "failure_strategy": None,
        },
    )
    row["node_id"] = node_id
    if state:
        row["state"] = state
    return row


def _mark_non_terminal_nodes(
    by_node: Dict[str, Dict[str, Any]],
    *,
    state: str,
    finished_ts: str,
) -> None:
    for row in by_node.values():
        if (row.get("state") or "").lower() in _TERMINAL_TIMELINE_STATES:
            continue
        row["state"] = state
        row["finished_at"] = finished_ts


def _handle_node_scheduled_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    **_: Any,
) -> None:
    if node_id and node_id not in by_node:
        _ensure_timeline_node(by_node, retry_counts, node_id, state="pending")


def _handle_node_started_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    finished_ts: str,
    **_: Any,
) -> None:
    if not node_id:
        return
    row = _ensure_timeline_node(by_node, retry_counts, node_id, state="running")
    row["started_at"] = finished_ts


def _handle_node_succeeded_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    payload: Dict[str, Any],
    finished_ts: str,
    **_: Any,
) -> None:
    if not node_id:
        return
    row = _ensure_timeline_node(by_node, retry_counts, node_id, state="success")
    row["finished_at"] = finished_ts
    row["duration_ms"] = payload.get("duration_ms")
    row["error_message"] = None
    row["error_type"] = None
    row["error_stack"] = None
    row["failure_strategy"] = None


def _handle_node_failed_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    payload: Dict[str, Any],
    finished_ts: str,
    **_: Any,
) -> None:
    if not node_id:
        return
    row = _ensure_timeline_node(by_node, retry_counts, node_id, state="failed")
    row["finished_at"] = finished_ts
    row["error_message"] = payload.get("error_message")
    row["error_type"] = payload.get("error_type")
    row["error_stack"] = payload.get("stack_trace")
    row["failure_strategy"] = payload.get("failure_strategy")
    row["retry_count"] = payload.get("retry_count", 0)


def _handle_node_timeout_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    finished_ts: str,
    **_: Any,
) -> None:
    if not node_id:
        return
    row = _ensure_timeline_node(by_node, retry_counts, node_id, state="timeout")
    row["finished_at"] = finished_ts


def _handle_node_skipped_event(
    *,
    node_id: str,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
    finished_ts: str,
    **_: Any,
) -> None:
    if not node_id:
        return
    row = _ensure_timeline_node(by_node, retry_counts, node_id, state="skipped")
    row["finished_at"] = finished_ts


def _handle_node_retry_scheduled_event(
    *,
    node_id: str,
    retry_counts: Dict[str, int],
    **_: Any,
) -> None:
    if node_id:
        retry_counts[node_id] = retry_counts.get(node_id, 0) + 1


_NODE_TIMELINE_EVENT_HANDLERS = {
    ExecutionEventType.NODE_SCHEDULED: _handle_node_scheduled_event,
    ExecutionEventType.NODE_STARTED: _handle_node_started_event,
    ExecutionEventType.NODE_SUCCEEDED: _handle_node_succeeded_event,
    ExecutionEventType.NODE_FAILED: _handle_node_failed_event,
    ExecutionEventType.NODE_TIMEOUT: _handle_node_timeout_event,
    ExecutionEventType.NODE_SKIPPED: _handle_node_skipped_event,
    ExecutionEventType.NODE_RETRY_SCHEDULED: _handle_node_retry_scheduled_event,
}


def _apply_timeline_event(
    *,
    ev: ExecutionEvent,
    by_node: Dict[str, Dict[str, Any]],
    retry_counts: Dict[str, int],
) -> None:
    payload = ev.payload or {}
    node_id = _event_node_id(payload)
    finished_ts = _timeline_ts_to_iso(ev.timestamp)

    node_handler = _NODE_TIMELINE_EVENT_HANDLERS.get(ev.event_type)
    if node_handler is not None:
        node_handler(
            node_id=node_id,
            by_node=by_node,
            retry_counts=retry_counts,
            payload=payload,
            finished_ts=finished_ts,
        )
        return

    if ev.event_type == ExecutionEventType.GRAPH_CANCELLED:
        _mark_non_terminal_nodes(by_node, state="cancelled", finished_ts=finished_ts)
        return

    if ev.event_type == ExecutionEventType.GRAPH_FAILED:
        _mark_non_terminal_nodes(by_node, state="failed", finished_ts=finished_ts)


def _build_node_timeline_from_events(events: List[ExecutionEvent]) -> List[Dict[str, Any]]:
    """
    从 execution_event 流构建 node_timeline，统一以事件为单一数据源。
    处理 NODE_SCHEDULED、NODE_STARTED 及节点终态事件；GRAPH_CANCELLED/GRAPH_FAILED 时将未终态节点回填。
    """
    by_node: Dict[str, Dict[str, Any]] = {}
    retry_counts: Dict[str, int] = {}

    for ev in events:
        _apply_timeline_event(ev=ev, by_node=by_node, retry_counts=retry_counts)

    for node_id, row in by_node.items():
        current_retry = int(row.get("retry_count") or 0)
        row["retry_count"] = max(current_retry, retry_counts.get(node_id, 0))
        row.setdefault("started_at", None)
        row.setdefault("finished_at", None)
        row.setdefault("duration_ms", None)
        row.setdefault("error_message", None)
        row.setdefault("error_type", None)
        row.setdefault("error_stack", None)
        row.setdefault("failure_strategy", None)

    return list(by_node.values())


async def _node_timeline_from_event_store(instance_id: str) -> Optional[List[Dict[str, Any]]]:
    """从 execution_event 表拉取事件并构建 node_timeline；失败或无事件时返回 None。"""
    try:
        kernel_db = Database()
        async with kernel_db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id=instance_id)
        if not events:
            return None
        return _build_node_timeline_from_events(events)
    except Exception as e:
        logger.debug(
            f"[WorkflowAPI] node_timeline from events skipped: instance_id={instance_id} err={e}"
        )
        return None


def _parse_query_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        candidate = str(value).strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _workflow_error_log_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _build_error_row_from_event(ev: ExecutionEvent, execution_id: str) -> Optional[Dict[str, Any]]:
    payload = ev.payload or {}
    node = str(payload.get("node_id") or "").strip()
    if not node:
        return None
    ts_iso = _timeline_ts_to_iso(ev.timestamp)
    return {
        "execution_id": execution_id,
        "event_id": ev.event_id,
        "sequence": ev.sequence,
        "timestamp": ts_iso,
        "node_id": node,
        "event_type": ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type),
        "error_message": _workflow_error_log_optional_str(payload.get("error_message")),
        "error_type": _workflow_error_log_optional_str(payload.get("error_type")),
        "error_stack": _workflow_error_log_optional_str(payload.get("stack_trace")),
        "failure_strategy": _workflow_error_log_optional_str(payload.get("failure_strategy")),
        "retry_count": int(payload.get("retry_count") or 0),
    }


def _error_row_match_filters(
    row: Dict[str, Any],
    *,
    node_id: Optional[str],
    error_type: Optional[str],
    failure_strategy: Optional[str],
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> bool:
    if node_id and str(row.get("node_id") or "") != str(node_id):
        return False
    if error_type and str(row.get("error_type") or "") != str(error_type):
        return False
    if failure_strategy and str(row.get("failure_strategy") or "") != str(failure_strategy):
        return False
    if start_dt or end_dt:
        row_dt = _parse_query_iso_datetime(str(row.get("timestamp") or ""))
        if row_dt is None:
            return False
        if start_dt and row_dt < start_dt:
            return False
        if end_dt and row_dt > end_dt:
            return False
    return True


async def _execution_error_logs_from_event_store(
    *,
    instance_id: str,
    execution_id: str,
    node_id: Optional[str],
    error_type: Optional[str],
    failure_strategy: Optional[str],
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> List[Dict[str, Any]]:
    try:
        kernel_db = Database()
        async with kernel_db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id=instance_id)
        out: List[Dict[str, Any]] = []
        for ev in events or []:
            if ev.event_type not in {ExecutionEventType.NODE_FAILED, ExecutionEventType.NODE_TIMEOUT}:
                continue
            row = _build_error_row_from_event(ev, execution_id=execution_id)
            if not isinstance(row, dict):
                continue
            if not _error_row_match_filters(
                row,
                node_id=node_id,
                error_type=error_type,
                failure_strategy=failure_strategy,
                start_dt=start_dt,
                end_dt=end_dt,
            ):
                continue
            out.append(row)
        return out
    except Exception as e:
        logger.debug(
            f"[WorkflowAPI] execution error logs from events skipped: instance_id={instance_id} err={e}"
        )
        return []


async def _execution_events_from_event_store(instance_id: str) -> List[Dict[str, Any]]:
    try:
        kernel_db = Database()
        async with kernel_db.async_session() as session:
            store = EventStore(session)
            events = await store.get_events(instance_id=instance_id)
        out: List[Dict[str, Any]] = []
        for ev in events or []:
            event_type = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)
            out.append(
                {
                    "event_id": ev.event_id,
                    "instance_id": ev.instance_id,
                    "sequence": ev.sequence,
                    "event_type": event_type,
                    "timestamp": ev.timestamp,
                    "payload": ev.payload or {},
                    "schema_version": getattr(ev, "schema_version", None),
                }
            )
        return out
    except Exception as e:
        logger.debug(
            f"[WorkflowAPI] execution events from events skipped: instance_id={instance_id} err={e}"
        )
        return []


def _build_failure_report_archive_bytes(
    *,
    report: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> bytes:
    report_sha256 = str(report.get("report_sha256") or "")
    schema = str(report.get("report_schema_version") or "unknown")
    redaction = "on" if bool(report.get("redaction_applied")) else "off"
    redacted_keys = int(report.get("redacted_key_count") or 0)
    audit_summary = f"schema={schema};redaction={redaction};redacted_keys={redacted_keys}"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        readme = (
            "Workflow Failure Bundle\n"
            "=======================\n\n"
            "- failure-report.json: Unified execution failure report payload.\n"
            "- failure-report.sha256: Hex digest of the canonical JSON (same algorithm as report.report_sha256).\n"
            "- execution-events.json: Raw execution event stream snapshot.\n\n"
            "Notes:\n"
            "- Timestamps are ISO8601 in UTC unless otherwise specified.\n"
            "- Sensitive fields may be masked by server-side redaction.\n"
            "- failure-report.json includes report_schema_version, redaction_applied, and redacted_key_count.\n"
            f"- audit_summary: {audit_summary}\n"
            f"- report_sha256: {report_sha256}\n"
        )
        zf.writestr("README.txt", readme)
        zf.writestr("failure-report.json", json.dumps(report, ensure_ascii=False, indent=2))
        if report_sha256:
            zf.writestr("failure-report.sha256", report_sha256 + "\n")
        zf.writestr("execution-events.json", json.dumps(events, ensure_ascii=False, indent=2))
    return buffer.getvalue()


def _redact_sensitive_value(value: Any) -> Any:
    redacted, _ = _redact_sensitive_value_with_count(value)
    return redacted


def _redact_sensitive_value_with_count(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        count = 0
        for key, raw in value.items():
            key_norm = str(key).strip().lower()
            if key_norm in SENSITIVE_FIELD_KEYS:
                out[key] = "***REDACTED***"
                count += 1
                continue
            redacted_raw, sub_count = _redact_sensitive_value_with_count(raw)
            out[key] = redacted_raw
            count += sub_count
        return out, count
    if isinstance(value, list):
        out_list: List[Any] = []
        count = 0
        for item in value:
            redacted_item, sub_count = _redact_sensitive_value_with_count(item)
            out_list.append(redacted_item)
            count += sub_count
        return out_list, count
    return value, 0


def _compute_report_sha256(report: Dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_sha256", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _merge_timeline_with_node_states(
    node_timeline_override: List[Dict[str, Any]],
    execution: WorkflowExecution,
) -> List[Dict[str, Any]]:
    """事件流部分缺失时用 node_states 补全，避免节点在 timeline 消失。"""
    seen = {r["node_id"] for r in node_timeline_override}
    out_list = list(node_timeline_override)
    for n in execution.node_states or []:
        if n.node_id in seen:
            continue
        duration_ms = None
        if n.started_at and n.finished_at:
            duration_ms = int((n.finished_at - n.started_at).total_seconds() * 1000)
        out_list.append({
            "node_id": n.node_id,
            "state": n.state.value if hasattr(n.state, "value") else str(n.state),
            "started_at": n.started_at.isoformat() if n.started_at else None,
            "finished_at": n.finished_at.isoformat() if n.finished_at else None,
            "duration_ms": duration_ms,
            "retry_count": n.retry_count,
            "error_message": n.error_message,
            "error_type": n.error_details.get("error_type") if isinstance(n.error_details, dict) else None,
            "error_stack": n.error_details.get("stack_trace") if isinstance(n.error_details, dict) else None,
            "failure_strategy": n.error_details.get("failure_strategy") if isinstance(n.error_details, dict) else None,
        })
    return out_list


def _node_duration_ms(node: WorkflowExecutionNode) -> Optional[int]:
    if node.started_at and node.finished_at:
        return int((node.finished_at - node.started_at).total_seconds() * 1000)
    return None


def _node_timeline_row(node: WorkflowExecutionNode) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "state": node.state.value if hasattr(node.state, "value") else str(node.state),
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "finished_at": node.finished_at.isoformat() if node.finished_at else None,
        "duration_ms": _node_duration_ms(node),
        "retry_count": node.retry_count,
        "error_message": node.error_message,
        "error_type": node.error_details.get("error_type") if isinstance(node.error_details, dict) else None,
        "error_stack": node.error_details.get("stack_trace") if isinstance(node.error_details, dict) else None,
        "failure_strategy": node.error_details.get("failure_strategy") if isinstance(node.error_details, dict) else None,
    }


def _agent_summary_from_node_output(
    node: WorkflowExecutionNode,
    duration_ms: Optional[int],
) -> Optional[Dict[str, Any]]:
    output = node.output_data or {}
    if not (isinstance(output, dict) and output.get("type") == "agent_result"):
        return None
    return {
        "node_id": node.node_id,
        "agent_id": output.get("agent_id"),
        "agent_session_id": output.get("agent_session_id"),
        "status": output.get("status", "success"),
        "response_preview": output.get("response_preview"),
        "recovery": output.get("recovery") if isinstance(output.get("recovery"), dict) else None,
        "duration_ms": duration_ms,
    }


def _execution_recovery_summaries(execution: WorkflowExecution) -> List[Dict[str, Any]]:
    recoveries: List[Dict[str, Any]] = []
    for node in execution.node_states or []:
        summary = _agent_summary_from_node_output(node, _node_duration_ms(node))
        if not isinstance(summary, dict):
            continue
        recovery = summary.get("recovery")
        if not isinstance(recovery, dict):
            continue
        recoveries.append(
            {
                "node_id": summary.get("node_id"),
                "agent_id": summary.get("agent_id"),
                "agent_session_id": summary.get("agent_session_id"),
                "recovery": recovery,
            }
        )
    return recoveries


def _execution_collaboration_summaries(execution: WorkflowExecution) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for node in execution.node_states or []:
        output = node.output_data or {}
        if not (isinstance(output, dict) and output.get("type") == "agent_result"):
            continue
        messages = output.get("collaboration_messages")
        if not isinstance(messages, list):
            continue
        summary = _summarize_collaboration_messages(node_id=node.node_id, output=output, messages=messages)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _summarize_collaboration_messages(
    *,
    node_id: str,
    output: Dict[str, Any],
    messages: List[Any],
) -> Optional[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = [m for m in messages if isinstance(m, dict)]
    if not normalized:
        return None
    status_counts: Dict[str, int] = {}
    stage_counts: Dict[str, int] = {}
    for msg in normalized:
        status = str(msg.get("status") or "unknown").strip().lower() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        content = msg.get("content")
        stage = str(content.get("stage") or "unknown").strip().lower() if isinstance(content, dict) else "unknown"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    return {
        "node_id": node_id,
        "agent_id": output.get("agent_id"),
        "agent_session_id": output.get("agent_session_id"),
        "message_total": len(normalized),
        "status_counts": status_counts,
        "stage_counts": stage_counts,
        "recent_messages": normalized[-20:],
    }


def _should_include_execution_in_call_chain(
    *,
    item: WorkflowExecution,
    root_execution_id: str,
    correlation_id: str,
) -> bool:
    item_ctx = item.global_context or {}
    item_correlation = str(item_ctx.get("correlation_id") or "").strip()
    parent_execution_id = str(item_ctx.get("parent_execution_id") or "").strip()
    if item.execution_id == root_execution_id:
        return True
    if item_correlation and item_correlation == correlation_id:
        return True
    if parent_execution_id and parent_execution_id == root_execution_id:
        return True
    return False


def _collect_node_timeline_and_agent_summaries(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]],
) -> tuple[List[WorkflowJsonRecord], List[WorkflowJsonRecord]]:
    node_timeline_raw: List[Dict[str, Any]]
    if node_timeline_override:
        node_timeline_raw = _merge_timeline_with_node_states(node_timeline_override, execution)
    else:
        node_timeline_raw = [_node_timeline_row(node) for node in (execution.node_states or [])]

    agent_summaries_raw: List[Dict[str, Any]] = []
    for node in execution.node_states or []:
        summary = _agent_summary_from_node_output(node, _node_duration_ms(node))
        if summary is not None:
            agent_summaries_raw.append(summary)

    if not agent_summaries_raw and isinstance(execution.output_data, dict):
        fallback = execution.output_data.get("agent_summaries")
        if isinstance(fallback, list):
            agent_summaries_raw = [x for x in fallback if isinstance(x, dict)]

    return (
        _as_workflow_json_records(node_timeline_raw),
        _as_workflow_json_records(agent_summaries_raw),
    )


def _execution_to_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionResponse:
    """转换 WorkflowExecution 为响应格式；node_timeline_override 非空时以事件流为主，并与 node_states 合并补全缺失节点。"""
    node_states = _as_workflow_json_records([n.model_dump(mode="json") for n in (execution.node_states or [])])
    node_timeline, agent_summaries = _collect_node_timeline_and_agent_summaries(
        execution=execution,
        node_timeline_override=node_timeline_override,
    )

    od = execution.output_data
    if od is None:
        output_data = None
    elif isinstance(od, dict):
        output_data = _as_workflow_json_map(od)
    else:
        output_data = None

    return WorkflowExecutionResponse(
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        version_id=execution.version_id,
        state=execution.state.value,
        graph_instance_id=execution.graph_instance_id,
        input_data=_as_workflow_json_map(execution.input_data),
        output_data=output_data,
        global_context=_as_workflow_json_map(execution.global_context or {}),
        trigger_type=execution.trigger_type,
        triggered_by=execution.triggered_by,
        error_message=execution.error_message,
        error_details=_as_optional_workflow_json_map(execution.error_details),
        created_at=execution.created_at.isoformat() if execution.created_at else "",
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
        duration_ms=execution.duration_ms,
        queue_position=execution.queue_position,
        queued_at=execution.queued_at.isoformat() if execution.queued_at else None,
        wait_duration_ms=execution.wait_duration_ms,
        node_states=node_states,
        node_timeline=node_timeline,
        replay=_as_workflow_json_map(
            {
                "execution_id": execution.execution_id,
                "graph_instance_id": execution.graph_instance_id,
                "replay_key": execution.graph_instance_id or execution.execution_id,
            }
        ),
        agent_summaries=agent_summaries,
    )


def _build_failure_report_payload(
    *,
    workflow_id: str,
    execution: WorkflowExecution,
    execution_payload: Dict[str, Any],
    error_rows: List[Dict[str, Any]],
    selected_node_id: Optional[str],
    error_type: Optional[str],
    failure_strategy: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
) -> Dict[str, Any]:
    error_details = execution.error_details if isinstance(execution.error_details, dict) else None
    recovery_actions = error_details.get("recovery_actions") if isinstance(error_details, dict) else None
    return {
        "report_schema_version": FAILURE_REPORT_SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "workflow_id": workflow_id,
        "execution_id": execution.execution_id,
        "execution_state": execution.state.value if hasattr(execution.state, "value") else str(execution.state),
        "trigger_type": execution.trigger_type,
        "triggered_by": execution.triggered_by,
        "created_at": execution_payload.get("created_at"),
        "started_at": execution_payload.get("started_at"),
        "finished_at": execution_payload.get("finished_at"),
        "duration_ms": execution.duration_ms,
        "queue_position": execution.queue_position,
        "wait_duration_ms": execution.wait_duration_ms,
        "global_context": execution.global_context or {},
        "global_error_details": error_details,
        "recovery_actions": recovery_actions if isinstance(recovery_actions, list) else [],
        "node_timeline": execution_payload.get("node_timeline") or [],
        "node_states": execution_payload.get("node_states") or [],
        "filtered_error_logs": error_rows,
        "filter_snapshot": {
            "selected_node_id": selected_node_id,
            "error_type": error_type,
            "failure_strategy": failure_strategy,
            "start_time": start_time,
            "end_time": end_time,
        },
        "execution": execution_payload,
    }


def _execution_to_status_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionStatusResponse:
    node_timeline_raw: List[Dict[str, Any]]
    if node_timeline_override:
        node_timeline_raw = _merge_timeline_with_node_states(node_timeline_override, execution)
    else:
        node_timeline_raw = [_node_timeline_row(n) for n in (execution.node_states or [])]
    node_timeline = _as_workflow_json_records(node_timeline_raw)
    return WorkflowExecutionStatusResponse(
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        version_id=execution.version_id,
        state=execution.state.value,
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
        duration_ms=execution.duration_ms,
        queue_position=execution.queue_position,
        wait_duration_ms=execution.wait_duration_ms,
        node_timeline=node_timeline,
    )


def _build_execution_call_chain(
    root_execution: WorkflowExecution,
    candidates: List[WorkflowExecution],
) -> tuple[str, List[WorkflowExecutionCallChainItem]]:
    root_ctx = root_execution.global_context or {}
    correlation_id = str(root_ctx.get("correlation_id") or f"wfex_{root_execution.execution_id}").strip()
    scoped: List[WorkflowExecution] = [
        item
        for item in candidates
        if _should_include_execution_in_call_chain(
            item=item,
            root_execution_id=root_execution.execution_id,
            correlation_id=correlation_id,
        )
    ]

    scoped.sort(
        key=lambda ex: (
            ex.created_at.isoformat() if ex.created_at else "",
            ex.execution_id,
        )
    )
    items: List[WorkflowExecutionCallChainItem] = []
    for ex in scoped:
        ctx = ex.global_context or {}
        items.append(
            WorkflowExecutionCallChainItem(
                execution_id=ex.execution_id,
                workflow_id=ex.workflow_id,
                version_id=ex.version_id,
                state=ex.state.value,
                created_at=ex.created_at.isoformat() if ex.created_at else None,
                started_at=ex.started_at.isoformat() if ex.started_at else None,
                finished_at=ex.finished_at.isoformat() if ex.finished_at else None,
                parent_execution_id=ctx.get("parent_execution_id"),
                parent_node_id=ctx.get("parent_node_id"),
                correlation_id=ctx.get("correlation_id"),
                recovery_summaries=_as_workflow_json_records(_execution_recovery_summaries(ex)),
                collaboration_summaries=_as_workflow_json_records(_execution_collaboration_summaries(ex)),
            )
        )
    return correlation_id, items


def _map_kernel_graph_state_to_workflow_state(kernel_state: str) -> Optional[str]:
    s = str(kernel_state or "").strip().lower()
    mapping = {
        "running": WorkflowExecutionState.RUNNING.value,
        "pending": WorkflowExecutionState.PENDING.value,
        "completed": WorkflowExecutionState.COMPLETED.value,
        "failed": WorkflowExecutionState.FAILED.value,
        "cancelled": WorkflowExecutionState.CANCELLED.value,
    }
    return mapping.get(s)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _map_kernel_node_state(state_raw: Any) -> WorkflowExecutionNodeState:
    normalized = str(state_raw or "pending").lower()
    state_map = {
        "success": WorkflowExecutionNodeState.SUCCESS,
        "running": WorkflowExecutionNodeState.RUNNING,
        "failed": WorkflowExecutionNodeState.FAILED,
        "skipped": WorkflowExecutionNodeState.SKIPPED,
        "cancelled": WorkflowExecutionNodeState.CANCELLED,
        "timeout": WorkflowExecutionNodeState.TIMEOUT,
    }
    return state_map.get(normalized, WorkflowExecutionNodeState.PENDING)


def _hydrate_node_from_kernel_item(item: Any) -> Optional[WorkflowExecutionNode]:
    if not isinstance(item, dict):
        return None
    return WorkflowExecutionNode(
        node_id=str(item.get("node_id") or ""),
        state=_map_kernel_node_state(item.get("state")),
        input_data=item.get("input_data") or {},
        output_data=item.get("output_data") or {},
        error_message=item.get("error_message"),
        error_details=item.get("error_details") if isinstance(item.get("error_details"), dict) else None,
        started_at=_parse_iso_datetime(item.get("started_at")),
        finished_at=_parse_iso_datetime(item.get("finished_at")),
        retry_count=int(item.get("retry_count") or 0),
    )


def _hydrate_nodes_from_kernel(raw_nodes: Any) -> List[WorkflowExecutionNode]:
    hydrated: List[WorkflowExecutionNode] = []
    for item in raw_nodes or []:
        node = _hydrate_node_from_kernel_item(item)
        if node is not None:
            hydrated.append(node)
    return hydrated


def _update_execution_timing_from_nodes(execution: WorkflowExecution) -> None:
    if execution.finished_at is None:
        finished_candidates = [n.finished_at for n in (execution.node_states or []) if n.finished_at]
        execution.finished_at = max(finished_candidates) if finished_candidates else datetime.now(UTC)
    if execution.started_at and execution.finished_at:
        execution.duration_ms = int((execution.finished_at - execution.started_at).total_seconds() * 1000)


def _apply_kernel_state_to_execution(execution: WorkflowExecution, result: Dict[str, Any]) -> None:
    kernel_state = _map_kernel_graph_state_to_workflow_state(cast(str, result.get("state") or ""))
    if not kernel_state:
        return
    execution.state = WorkflowExecutionState(kernel_state)
    if execution.state in {
        WorkflowExecutionState.COMPLETED,
        WorkflowExecutionState.FAILED,
        WorkflowExecutionState.CANCELLED,
        WorkflowExecutionState.TIMEOUT,
    }:
        _update_execution_timing_from_nodes(execution)


def _apply_terminal_state_from_nodes(execution: WorkflowExecution) -> None:
    # 边界兜底：若图状态尚未刷新，但节点已经全终态，则以节点终态覆盖 response 视图。
    terminal_from_nodes = _derive_terminal_state_from_nodes(execution.node_states or [])
    if terminal_from_nodes is None:
        return
    execution.state = terminal_from_nodes
    _update_execution_timing_from_nodes(execution)


async def _hydrate_execution_live_from_kernel(execution: WorkflowExecution) -> WorkflowExecution:
    """
    运行中实时回填：
    - 从 execution_kernel 读取 node_runtimes / graph_state
    - 覆盖 response 用 execution.node_states / state / output_data，避免前端看到陈旧状态
    """
    if not execution.graph_instance_id:
        return execution

    try:
        kernel_db = Database()
        result = await GraphRuntimeAdapter.extract_execution_result_from_kernel(
            execution.graph_instance_id,
            kernel_db,
        )
    except Exception as e:
        logger.debug(f"[WorkflowAPI] live hydrate skipped: execution_id={execution.execution_id} err={e}")
        return execution

    if not isinstance(result, dict):
        return execution

    # 1) 节点状态实时回填
    hydrated_nodes = _hydrate_nodes_from_kernel(result.get("node_states") or [])
    if hydrated_nodes:
        execution.node_states = hydrated_nodes

    # 2) 图状态实时回填（response 级别）
    _apply_kernel_state_to_execution(execution, result)
    _apply_terminal_state_from_nodes(execution)

    # 3) 输出实时回填
    if isinstance(result.get("output_data"), dict) and result.get("output_data"):
        execution.output_data = cast(Dict[str, Any], result.get("output_data"))

    return execution


def _derive_terminal_state_from_nodes(nodes: List[WorkflowExecutionNode]) -> Optional[WorkflowExecutionState]:
    if not nodes:
        return None
    states = [n.state for n in nodes]
    terminal = {
        WorkflowExecutionNodeState.SUCCESS,
        WorkflowExecutionNodeState.FAILED,
        WorkflowExecutionNodeState.SKIPPED,
        WorkflowExecutionNodeState.CANCELLED,
        WorkflowExecutionNodeState.TIMEOUT,
    }
    if not all(s in terminal for s in states):
        return None
    if any(s in {WorkflowExecutionNodeState.FAILED, WorkflowExecutionNodeState.TIMEOUT} for s in states):
        return WorkflowExecutionState.FAILED
    if any(s == WorkflowExecutionNodeState.CANCELLED for s in states):
        return WorkflowExecutionState.CANCELLED
    return WorkflowExecutionState.COMPLETED


def _maybe_persist_terminal_reconcile(
    execution_service: WorkflowExecutionService,
    live_execution: WorkflowExecution,
) -> WorkflowExecution:
    """
    当 live 视图显示已终态而 workflow_executions 仍 running/pending 时，做一次幂等回写。
    """
    terminal_state = _derive_terminal_state_from_nodes(live_execution.node_states or [])
    if terminal_state is None:
        return live_execution
    now = datetime.now(UTC)
    lock_until = _TERMINAL_RECONCILE_LOCK_UNTIL.get(live_execution.execution_id)
    if lock_until and now < lock_until:
        return live_execution
    try:
        # 先收敛主状态，确保前端尽快从 running 进入终态；重数据字段做 best-effort。
        _recon_tid = str(getattr(live_execution, "tenant_id", None) or "default").strip() or "default"
        persisted = execution_service.repository.update_state(
            live_execution.execution_id,
            terminal_state,
            tenant_id=_recon_tid,
        )
        try:
            execution_service.repository.update_node_states(
                live_execution.execution_id,
                live_execution.node_states or [],
                tenant_id=_recon_tid,
            )
            if isinstance(live_execution.output_data, dict):
                execution_service.repository.update_output(
                    live_execution.execution_id,
                    live_execution.output_data,
                    tenant_id=_recon_tid,
                )
        except OperationalError as oe:
            if "database is locked" in str(oe).lower():
                _TERMINAL_RECONCILE_LOCK_UNTIL[live_execution.execution_id] = now + timedelta(seconds=5)
                logger.debug(
                    f"[WorkflowAPI] Terminal reconcile payload skipped due to DB lock: "
                    f"execution_id={live_execution.execution_id}"
                )
            else:
                raise
        if persisted:
            _TERMINAL_RECONCILE_LOCK_UNTIL.pop(live_execution.execution_id, None)
            logger.info(
                f"[WorkflowAPI] Reconciled terminal state from live kernel: "
                f"execution_id={live_execution.execution_id} state={terminal_state.value}"
            )
            return persisted
    except OperationalError as e:
        if "database is locked" in str(e).lower():
            _TERMINAL_RECONCILE_LOCK_UNTIL[live_execution.execution_id] = now + timedelta(seconds=5)
            logger.debug(
                f"[WorkflowAPI] Terminal reconcile deferred by DB lock: "
                f"execution_id={live_execution.execution_id}"
            )
            return live_execution
        logger.warning(
            f"[WorkflowAPI] Terminal reconcile skipped: execution_id={live_execution.execution_id} err={e}"
        )
    except Exception as e:
        logger.warning(
            f"[WorkflowAPI] Terminal reconcile skipped: execution_id={live_execution.execution_id} err={e}"
        )
    return live_execution
