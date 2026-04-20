"""
审计日志查询 API（仅 admin）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.data.base import get_db
from core.security.audit_service import query_audit_logs
from core.security.deps import require_audit_reader

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


class AuditLogItem(BaseModel):
    id: str
    created_at: Optional[str]
    tenant_id: Optional[str] = None
    user_id: str
    platform_role: str
    method: str
    path: str
    status_code: int
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    client_ip: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


class AuditLogListResponse(BaseModel):
    items: List[AuditLogItem]
    total: int
    limit: int
    offset: int


@router.get("/logs", response_model=AuditLogListResponse)
def list_audit_logs(
    request: Request,
    db: Session = Depends(get_db),
    _role=Depends(require_audit_reader),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[str] = None,
    path_prefix: Optional[str] = None,
    method: Optional[str] = None,
    since_iso: Optional[str] = Query(default=None, description="ISO8601 起始时间（可选）"),
):
    since_dt = None
    if since_iso:
        try:
            since_dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        except ValueError:
            since_dt = None
    items, total = query_audit_logs(
        db,
        tenant_id=getattr(request.state, "tenant_id", None),
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
