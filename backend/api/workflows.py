"""
Workflow API Endpoints

Workflow Control Plane 的 REST API 接口。
"""

from typing import Annotated, List, Optional, Dict, Any, Union, AsyncIterator, Callable, cast
import asyncio
import json
import hashlib
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, Query, status, BackgroundTasks, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
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
from core.workflows.runtime import WorkflowRuntime
from core.workflows.debug_runtime import (
    kernel_debug_snapshot as _kernel_debug_snapshot_helper,
    recent_events_debug as _recent_events_debug_helper,
)
from core.workflows.tenant_guard import resolve_tenant_id, namespace_matches_tenant
from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter
from config.settings import settings
from middleware.user_context import get_current_user
from core.data.base import get_db, SessionLocal
from core.idempotency.service import IdempotencyService
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
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]] = None
    global_context: Dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = "manual"
    triggered_by: Optional[str] = None
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    queue_position: Optional[int] = None
    queued_at: Optional[str] = None
    wait_duration_ms: Optional[int] = None
    node_states: List[Dict[str, Any]] = Field(default_factory=list)
    node_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    replay: Dict[str, Any] = Field(default_factory=dict)
    agent_summaries: List[Dict[str, Any]] = Field(default_factory=list)


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
    node_timeline: List[Dict[str, Any]] = Field(default_factory=list)


class WorkflowApprovalTaskResponse(BaseModel):
    id: str
    execution_id: str
    workflow_id: str
    node_id: str
    title: Optional[str] = None
    reason: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
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


class ListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


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
        payload=row.payload or {},
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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


@router.get("", response_model=ListResponse)
async def list_workflows(
    http_request: Request,
    namespace: Optional[str] = None,
    lifecycle_state: Optional[WorkflowLifecycleState] = None,
    limit: Annotated[int, Query(le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> ListResponse:
    """列出工作流"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    
    return ListResponse(
        items=[_workflow_to_response(w).model_dump() for w in workflows],
        total=total,
        limit=limit,
        offset=offset
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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


@router.get("/{workflow_id}/versions", response_model=ListResponse)
async def list_versions(
    http_request: Request,
    workflow_id: str,
    state: Optional[WorkflowVersionState] = None,
    limit: Annotated[int, Query(le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> ListResponse:
    """列出工作流版本"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    
    return ListResponse(
        items=[_version_to_response(v).model_dump() for v in versions],
        total=total,
        limit=limit,
        offset=offset
    )


# 必须在 /{version_id} 之前注册，否则路径 .../versions/compare 会被当成 version_id="compare"
@router.get("/{workflow_id}/versions/compare", response_model=Dict[str, Any])
async def diff_versions(
    http_request: Request,
    workflow_id: str,
    from_version_id: Annotated[str, Query(description="Base version id")],
    to_version_id: Annotated[str, Query(description="Target version id")],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Dict[str, Any]:
    """比较两个版本的 DAG 差异"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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

    return {
        "workflow_id": workflow_id,
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "summary": {
            "node_added": len(added_nodes),
            "node_removed": len(removed_nodes),
            "node_changed": len(changed_nodes),
            "edge_added": len(added_edges),
            "edge_removed": len(removed_edges),
        },
        "nodes": {
            "added": added_nodes,
            "removed": removed_nodes,
            "changed": changed_nodes,
        },
        "edges": {
            "added": added_edges,
            "removed": removed_edges,
        },
    }


@router.get("/{workflow_id}/versions/{version_id}", response_model=Dict[str, Any])
async def get_version(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> Dict[str, Any]:
    """获取版本详情（包含 DAG）"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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

    return {
        **_version_to_response(version).model_dump(),
        "dag": version.dag.model_dump(),
        "checksum": version.checksum
    }


@router.post("/{workflow_id}/versions/{version_id}/publish", response_model=WorkflowVersionResponse)
async def publish_version(
    http_request: Request,
    workflow_id: str,
    version_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> WorkflowVersionResponse:
    """发布版本"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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


async def _run_execution_background(exec_id: str) -> None:
    logger.info(f"[WorkflowAPI] Background run start: execution_id={exec_id}")
    db_bg: Session = SessionLocal()
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
) -> None:
    # 优先直接投递事件循环，避免依赖 BackgroundTasks 触发时机导致 execution 长期停留 pending。
    try:
        task = asyncio.create_task(_run_execution_background(execution_id))
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
        background_tasks.add_task(_run_execution_background, execution_id)


async def _resolve_idempotent_execution_hit(
    *,
    claim: Any,
    execution_service: WorkflowExecutionService,
    workflow_id: str,
) -> WorkflowExecutionResponse:
    if claim.record.response_ref:
        ex = execution_service.get_execution(claim.record.response_ref)
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
        )
    
    return _execution_to_response(execution)


@router.get("/{workflow_id}/executions", response_model=ListResponse)
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
) -> ListResponse:
    """列出执行记录"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
        offset=offset
    )
    total = execution_service.count_executions(
        workflow_id=workflow_id,
        state=state,
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
    
    return ListResponse(
        items=[_execution_to_response(e).model_dump() for e in executions],
        total=total,
        limit=limit,
        offset=offset
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
    
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")
        raise AssertionError("unreachable")

    execution = await _hydrate_execution_live_from_kernel(execution)
    if reconcile:
        execution = _maybe_persist_terminal_reconcile(execution_service, execution)
    node_timeline_override = None
    if execution.graph_instance_id:
        node_timeline_override = await _node_timeline_from_event_store(execution.graph_instance_id)
    return _execution_to_response(execution, node_timeline_override=node_timeline_override)


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


@router.get("/{workflow_id}/executions/{execution_id}/debug")
async def get_execution_debug(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    event_limit: Annotated[int, Query(ge=1, le=500)] = 80,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Dict[str, Any]:
    """
    工作流调试视图：聚合 hydrated 执行详情、内核快照与 execution_kernel 近期事件。
    需对工作流具有 read 权限。
    """
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
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

    return {
        "execution": _execution_to_response(
            execution, node_timeline_override=node_timeline_override
        ).model_dump(),
        "kernel_snapshot": kernel_snapshot,
        "recent_events": recent_events,
        "debug": {
            "graph_instance_id": execution.graph_instance_id,
            "replay_hint": execution.graph_instance_id or execution.execution_id,
        },
    }


@router.delete("/{workflow_id}/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    http_request: Request,
    workflow_id: str,
    execution_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Response:
    """删除单个执行历史（仅允许终态）"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
        raise AssertionError("unreachable")
    try:
        deleted = execution_service.delete_execution(execution_id)
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
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


async def _load_execution_status_payload(
    *,
    execution_id: str,
    workflow_id: str,
    loop_exec_svc: WorkflowExecutionService,
) -> tuple[Optional[Dict[str, Any]], Optional[bool], Optional[str]]:
    current = loop_exec_svc.get_execution(execution_id)
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
) -> tuple[Optional[str], Optional[str], datetime]:
    if current_hash != last_hash:
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )


async def _stream_status_tick(
    *,
    workflow_id: str,
    execution_id: str,
    last_hash: Optional[str],
    heartbeat_at: datetime,
    heartbeat_every: int,
) -> tuple[Optional[str], Optional[str], datetime, bool]:
    loop_db = SessionLocal()
    try:
        loop_exec_svc = WorkflowExecutionService(loop_db)
        status_payload, is_terminal, error_message = await _load_execution_status_payload(
            execution_id=execution_id,
            workflow_id=workflow_id,
            loop_exec_svc=loop_exec_svc,
        )
        if error_message:
            return _sse_data({"type": "error", "message": error_message}), last_hash, heartbeat_at, True
        if status_payload is None or is_terminal is None:
            return _sse_data({"type": "error", "message": MSG_EXECUTION_NOT_FOUND}), last_hash, heartbeat_at, True

        current_hash = json.dumps(status_payload, ensure_ascii=False, sort_keys=True)
        now = datetime.now(UTC)
        event, next_hash, next_heartbeat_at = _build_status_or_heartbeat_event(
            current_hash=current_hash,
            last_hash=last_hash,
            heartbeat_at=heartbeat_at,
            now=now,
            heartbeat_every=heartbeat_every,
            status_payload=status_payload,
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
    interval_ms: Annotated[int, Query(ge=300, le=5000, description="SSE 推送间隔（毫秒）")] = 900,
    *,
    current_user: Annotated[str, Depends(get_current_user)],
) -> StreamingResponse:
    """SSE 推送执行状态（节点级），前端可替代高频轮询；轮询仍可作为降级路径。"""
    init_db = SessionLocal()
    try:
        _validate_stream_access(
            init_db=init_db,
            http_request=http_request,
            workflow_id=workflow_id,
            execution_id=execution_id,
            current_user=current_user,
        )
    finally:
        init_db.close()

    async def _event_stream() -> AsyncIterator[str]:
        last_hash: Optional[str] = None
        heartbeat_every = 15
        heartbeat_at = datetime.now(UTC)
        sleep_s = max(0.3, interval_ms / 1000.0)

        while True:
            try:
                event, last_hash, heartbeat_at, should_stop = await _stream_status_tick(
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    last_hash=last_hash,
                    heartbeat_at=heartbeat_at,
                    heartbeat_every=heartbeat_every,
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
                yield _sse_data({"type": "error", "message": str(e)})
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
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
        execution = execution_service.get_execution(execution_id)
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    execution = execution_service.get_execution(execution_id)
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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

    execution = WorkflowExecutionService(db).get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    items = [_approval_task_to_response(x) for x in service.list_for_execution(execution_id)]
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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

    execution = WorkflowExecutionService(db).get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    decision = service.approve(execution_id=execution_id, task_id=task_id, decided_by=current_user)
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
    execution_after = WorkflowExecutionService(db).get_execution(execution_id)
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
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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

    execution = WorkflowExecutionService(db).get_execution(execution_id)
    if not execution or execution.workflow_id != workflow_id:
        raise_api_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_execution_not_found",
            message=MSG_EXECUTION_NOT_FOUND,
            details={"workflow_id": workflow_id, "execution_id": execution_id},
        )
    service = WorkflowApprovalService(db)
    decision = service.reject(execution_id=execution_id, task_id=task_id, decided_by=current_user)
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
    execution_after = WorkflowExecutionService(db).get_execution(execution_id)
    execution_state = execution_after.state.value if execution_after else None
    return _approval_task_to_response(decision.task, execution_state_after_decision=execution_state)


# ==================== Quota Endpoints ====================

@router.get("/{workflow_id}/quota", response_model=Dict[str, Any])
async def get_quota_status(
    http_request: Request,
    workflow_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> Dict[str, Any]:
    """获取配额状态"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    return execution_manager.get_workflow_status(workflow_id)


@router.put("/{workflow_id}/quota", response_model=Dict[str, Any])
async def set_quota(
    http_request: Request,
    workflow_id: str,
    config: QuotaConfig,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)]
) -> Dict[str, Any]:
    """设置配额"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    
    return execution_manager.get_workflow_status(workflow_id)


@router.get("/{workflow_id}/governance", response_model=Dict[str, Any])
async def get_governance_config(
    http_request: Request,
    workflow_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Dict[str, Any]:
    """获取 workflow 执行治理参数与状态（队列/背压/并发）"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    return execution_manager.get_workflow_status(workflow_id)


@router.put("/{workflow_id}/governance", response_model=Dict[str, Any])
async def set_governance_config(
    http_request: Request,
    workflow_id: str,
    config: WorkflowGovernanceConfigRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> Dict[str, Any]:
    """设置 workflow 执行治理参数（队列/背压）"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    )
    return new_status


@router.get("/{workflow_id}/governance/audits", response_model=ListResponse)
async def list_governance_audits(
    http_request: Request,
    workflow_id: str,
    limit: Annotated[int, Query(le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[str, Depends(get_current_user)],
) -> ListResponse:
    """获取 workflow 治理配置变更审计记录"""
    tenant_id = resolve_tenant_id(http_request, default_tenant=getattr(settings, "tenant_default_id", "default"))
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
    items = audit_repo.list_audits(workflow_id, limit=limit, offset=offset)
    total = audit_repo.count_audits(workflow_id)
    return ListResponse(items=items, total=total, limit=limit, offset=offset)


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
        "duration_ms": duration_ms,
    }


def _collect_node_timeline_and_agent_summaries(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    node_timeline: List[Dict[str, Any]]
    if node_timeline_override:
        node_timeline = _merge_timeline_with_node_states(node_timeline_override, execution)
    else:
        node_timeline = [_node_timeline_row(node) for node in (execution.node_states or [])]

    agent_summaries: List[Dict[str, Any]] = []
    for node in execution.node_states or []:
        summary = _agent_summary_from_node_output(node, _node_duration_ms(node))
        if summary is not None:
            agent_summaries.append(summary)

    if not agent_summaries and isinstance(execution.output_data, dict):
        fallback = execution.output_data.get("agent_summaries")
        if isinstance(fallback, list):
            agent_summaries = fallback

    return node_timeline, agent_summaries


def _execution_to_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionResponse:
    """转换 WorkflowExecution 为响应格式；node_timeline_override 非空时以事件流为主，并与 node_states 合并补全缺失节点。"""
    node_states = [n.model_dump(mode="json") for n in (execution.node_states or [])]
    node_timeline, agent_summaries = _collect_node_timeline_and_agent_summaries(
        execution=execution,
        node_timeline_override=node_timeline_override,
    )

    return WorkflowExecutionResponse(
        execution_id=execution.execution_id,
        workflow_id=execution.workflow_id,
        version_id=execution.version_id,
        state=execution.state.value,
        graph_instance_id=execution.graph_instance_id,
        input_data=execution.input_data,
        output_data=execution.output_data,
        global_context=execution.global_context or {},
        trigger_type=execution.trigger_type,
        triggered_by=execution.triggered_by,
        error_message=execution.error_message,
        error_details=execution.error_details,
        created_at=execution.created_at.isoformat() if execution.created_at else "",
        started_at=execution.started_at.isoformat() if execution.started_at else None,
        finished_at=execution.finished_at.isoformat() if execution.finished_at else None,
        duration_ms=execution.duration_ms,
        queue_position=execution.queue_position,
        queued_at=execution.queued_at.isoformat() if execution.queued_at else None,
        wait_duration_ms=execution.wait_duration_ms,
        node_states=node_states,
        node_timeline=node_timeline,
        replay={
            "execution_id": execution.execution_id,
            "graph_instance_id": execution.graph_instance_id,
            "replay_key": execution.graph_instance_id or execution.execution_id,
        },
        agent_summaries=agent_summaries,
    )


def _execution_to_status_response(
    execution: WorkflowExecution,
    node_timeline_override: Optional[List[Dict[str, Any]]] = None,
) -> WorkflowExecutionStatusResponse:
    node_timeline: List[Dict[str, Any]] = []
    if node_timeline_override:
        node_timeline = _merge_timeline_with_node_states(node_timeline_override, execution)
    else:
        node_timeline = [_node_timeline_row(n) for n in (execution.node_states or [])]
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
        persisted = execution_service.repository.update_state(
            live_execution.execution_id,
            terminal_state,
        )
        try:
            execution_service.repository.update_node_states(
                live_execution.execution_id,
                live_execution.node_states or [],
            )
            if isinstance(live_execution.output_data, dict):
                execution_service.repository.update_output(
                    live_execution.execution_id,
                    live_execution.output_data,
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
