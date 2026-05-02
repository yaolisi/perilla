from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, cast

from sqlalchemy.orm import Session

from core.data.models.workflow import WorkflowApprovalTaskORM


class WorkflowApprovalTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _set_row_fields(row: WorkflowApprovalTaskORM, **fields: object) -> None:
        for key, value in fields.items():
            setattr(row, key, value)

    @staticmethod
    def _filter_tenant(q, tenant_id: Optional[str]):
        if tenant_id is None:
            return q
        tid = (str(tenant_id).strip() or "default")
        return q.filter(WorkflowApprovalTaskORM.tenant_id == tid)

    def get_by_id(self, task_id: str, tenant_id: Optional[str] = None) -> Optional[WorkflowApprovalTaskORM]:
        q = self.db.query(WorkflowApprovalTaskORM).filter(WorkflowApprovalTaskORM.id == task_id)
        q = self._filter_tenant(q, tenant_id)
        return cast(Optional[WorkflowApprovalTaskORM], q.first())

    def list_by_execution(self, execution_id: str, tenant_id: Optional[str] = None) -> List[WorkflowApprovalTaskORM]:
        q = self.db.query(WorkflowApprovalTaskORM).filter(
            WorkflowApprovalTaskORM.execution_id == execution_id
        )
        q = self._filter_tenant(q, tenant_id)
        return cast(
            List[WorkflowApprovalTaskORM],
            q.order_by(WorkflowApprovalTaskORM.created_at.desc()).all(),
        )

    def list_pending_by_execution(
        self, execution_id: str, tenant_id: Optional[str] = None
    ) -> List[WorkflowApprovalTaskORM]:
        q = (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
        )
        q = self._filter_tenant(q, tenant_id)
        return cast(
            List[WorkflowApprovalTaskORM],
            q.order_by(WorkflowApprovalTaskORM.created_at.desc()).all(),
        )

    def get_pending_by_execution_node(
        self, execution_id: str, node_id: str, tenant_id: Optional[str] = None
    ) -> Optional[WorkflowApprovalTaskORM]:
        q = (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.node_id == node_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
        )
        q = self._filter_tenant(q, tenant_id)
        return cast(Optional[WorkflowApprovalTaskORM], q.first())

    def create_task(
        self,
        *,
        execution_id: str,
        workflow_id: str,
        node_id: str,
        title: Optional[str],
        reason: Optional[str],
        payload: Optional[Dict[str, Any]],
        requested_by: Optional[str],
        tenant_id: str = "default",
        expires_in_seconds: Optional[int] = None,
    ) -> WorkflowApprovalTaskORM:
        expires_at = None
        if expires_in_seconds is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(expires_in_seconds)))
        tid = (str(tenant_id).strip() or "default")
        row = WorkflowApprovalTaskORM(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            execution_id=execution_id,
            workflow_id=workflow_id,
            node_id=node_id,
            title=title,
            reason=reason,
            payload=payload or {},
            status="pending",
            requested_by=requested_by,
            expires_at=expires_at,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def expire_pending_tasks(self, execution_id: str, tenant_id: Optional[str] = None) -> int:
        now = datetime.now(timezone.utc)
        q = (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
            .filter(WorkflowApprovalTaskORM.expires_at.isnot(None))
            .filter(WorkflowApprovalTaskORM.expires_at < now)
        )
        q = self._filter_tenant(q, tenant_id)
        rows = q.all()
        for row in rows:
            self._set_row_fields(row, status="expired", updated_at=now)
        if rows:
            self.db.commit()
        return len(rows)

    def decide(
        self,
        *,
        task_id: str,
        decision: str,
        decided_by: Optional[str],
        tenant_id: Optional[str] = None,
    ) -> Optional[WorkflowApprovalTaskORM]:
        row = self.get_by_id(task_id, tenant_id)
        if not row:
            return None
        if row.status != "pending":
            return row
        now = datetime.now(timezone.utc)
        self._set_row_fields(
            row,
            status="approved" if decision == "approved" else "rejected",
            decided_by=decided_by,
            decided_at=now,
            updated_at=now,
        )
        self.db.commit()
        self.db.refresh(row)
        return row
