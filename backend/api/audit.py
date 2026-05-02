"""
审计日志查询 API（仅 admin）
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from core.data.base import get_db
from core.security.audit_service import query_audit_logs
from core.security.deps import require_audit_reader
from core.utils.tenant_request import resolve_api_tenant_id

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditLogDetail(BaseModel):
    """审计附加载荷（结构随事件类型变化，OpenAPI 侧用命名 schema + additionalProperties）。"""

    model_config = ConfigDict(extra="allow")


class AuditLogItem(BaseModel):
    id: str
    created_at: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: str
    platform_role: str
    method: str
    path: str
    status_code: int
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    client_ip: Optional[str] = None
    detail: Optional[AuditLogDetail] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int
    limit: int
    offset: int


@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _role: Annotated[Any, Depends(require_audit_reader)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    user_id: Optional[str] = None,
    path_prefix: Optional[str] = None,
    method: Optional[str] = None,
    since_iso: Annotated[Optional[str], Query(description="ISO8601 起始时间（可选）")] = None,
) -> AuditLogListResponse:
    since_dt = None
    if since_iso:
        try:
            since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        except ValueError:
            since_dt = None
    items, total = query_audit_logs(
        db,
        tenant_id=resolve_api_tenant_id(request),
        limit=limit,
        offset=offset,
        user_id=user_id,
        path_prefix=path_prefix,
        method=method,
        since=since_dt,
    )
    return AuditLogListResponse(
        items=[AuditLogItem(**x) for x in items],
        total=total,
        limit=limit,
        offset=offset,
    )
