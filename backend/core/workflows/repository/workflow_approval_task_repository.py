from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.data.models.workflow import WorkflowApprovalTaskORM


class WorkflowApprovalTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, task_id: str) -> Optional[WorkflowApprovalTaskORM]:
        return self.db.query(WorkflowApprovalTaskORM).filter(WorkflowApprovalTaskORM.id == task_id).first()

    def list_by_execution(self, execution_id: str) -> List[WorkflowApprovalTaskORM]:
        return (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .order_by(WorkflowApprovalTaskORM.created_at.desc())
            .all()
        )

    def list_pending_by_execution(self, execution_id: str) -> List[WorkflowApprovalTaskORM]:
        return (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
            .order_by(WorkflowApprovalTaskORM.created_at.desc())
            .all()
        )

    def get_pending_by_execution_node(self, execution_id: str, node_id: str) -> Optional[WorkflowApprovalTaskORM]:
        return (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.node_id == node_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
            .first()
        )

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
        expires_in_seconds: Optional[int] = None,
    ) -> WorkflowApprovalTaskORM:
        expires_at = None
        if expires_in_seconds is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(expires_in_seconds)))
        row = WorkflowApprovalTaskORM(
            id=str(uuid.uuid4()),
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

    def expire_pending_tasks(self, execution_id: str) -> int:
        now = datetime.now(timezone.utc)
        rows = (
            self.db.query(WorkflowApprovalTaskORM)
            .filter(WorkflowApprovalTaskORM.execution_id == execution_id)
            .filter(WorkflowApprovalTaskORM.status == "pending")
            .filter(WorkflowApprovalTaskORM.expires_at.isnot(None))
            .filter(WorkflowApprovalTaskORM.expires_at < now)
            .all()
        )
        for row in rows:
            row.status = "expired"
            row.updated_at = now
        if rows:
            self.db.commit()
        return len(rows)

    def decide(self, *, task_id: str, decision: str, decided_by: Optional[str]) -> Optional[WorkflowApprovalTaskORM]:
        row = self.get_by_id(task_id)
        if not row:
            return None
        if row.status != "pending":
            return row
        row.status = "approved" if decision == "approved" else "rejected"
        row.decided_by = decided_by
        row.decided_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(row)
        return row
