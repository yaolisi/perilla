"""
审计日志查询与写入
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select, func
from sqlalchemy.orm import Session

from core.data.models.audit import AuditLogORM


def append_audit_log(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    platform_role: str,
    method: str,
    path: str,
    status_code: int,
    request_id: Optional[str],
    trace_id: Optional[str],
    client_ip: Optional[str],
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    row = AuditLogORM(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id or "default",
        user_id=user_id or "default",
        platform_role=platform_role or "operator",
        method=method,
        path=path[:2048] if path else "",
        status_code=int(status_code),
        request_id=(request_id[:64] if request_id else None),
        trace_id=(trace_id[:64] if trace_id else None),
        client_ip=(client_ip[:128] if client_ip else None),
        detail_json=json.dumps(detail, ensure_ascii=False)[:8000] if detail else None,
    )
    db.add(row)
    db.commit()


def query_audit_logs(
    db: Session,
    *,
    tenant_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    path_prefix: Optional[str] = None,
    method: Optional[str] = None,
    since: Optional[datetime] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    q = select(AuditLogORM)
    count_q = select(func.count()).select_from(AuditLogORM)
    if tenant_id:
        q = q.where(AuditLogORM.tenant_id == tenant_id)
        count_q = count_q.where(AuditLogORM.tenant_id == tenant_id)
    if user_id:
        q = q.where(AuditLogORM.user_id == user_id)
        count_q = count_q.where(AuditLogORM.user_id == user_id)
    if path_prefix:
        q = q.where(AuditLogORM.path.startswith(path_prefix))
        count_q = count_q.where(AuditLogORM.path.startswith(path_prefix))
    if method:
        q = q.where(AuditLogORM.method == method.upper())
        count_q = count_q.where(AuditLogORM.method == method.upper())
    if since:
        q = q.where(AuditLogORM.created_at >= since)
        count_q = count_q.where(AuditLogORM.created_at >= since)

    total = int(db.execute(count_q).scalar() or 0)
    q = q.order_by(desc(AuditLogORM.created_at)).offset(offset).limit(limit)
    rows = db.execute(q).scalars().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "user_id": r.user_id,
                "tenant_id": r.tenant_id,
                "platform_role": r.platform_role,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "request_id": r.request_id,
                "trace_id": r.trace_id,
                "client_ip": r.client_ip,
                "detail": json.loads(r.detail_json) if r.detail_json else None,
            }
        )
    return out, total
