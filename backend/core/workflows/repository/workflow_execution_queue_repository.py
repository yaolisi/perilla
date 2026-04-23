from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, cast

from sqlalchemy.orm import Session

from core.data.models.workflow import WorkflowExecutionQueueORM


class WorkflowExecutionQueueRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _set_row_fields(row: WorkflowExecutionQueueORM, **fields: object) -> None:
        for key, value in fields.items():
            setattr(row, key, value)

    def enqueue(self, *, execution_id: str, workflow_id: str, version_id: str, priority: int, queue_order: int) -> None:
        row = (
            self.db.query(WorkflowExecutionQueueORM)
            .filter(WorkflowExecutionQueueORM.execution_id == execution_id)
            .first()
        )
        now = datetime.now(timezone.utc)
        if row:
            self._set_row_fields(
                row,
                workflow_id=workflow_id,
                version_id=version_id,
                priority=int(priority),
                queue_order=int(queue_order),
                status="queued",
                lease_owner=None,
                lease_expire_at=None,
                updated_at=now,
            )
        else:
            row = WorkflowExecutionQueueORM(
                id=str(uuid.uuid4()),
                execution_id=execution_id,
                workflow_id=workflow_id,
                version_id=version_id,
                priority=int(priority),
                queue_order=int(queue_order),
                status="queued",
                queued_at=now,
                updated_at=now,
            )
            self.db.add(row)
        self.db.commit()

    def mark_done(self, execution_id: str) -> None:
        row = (
            self.db.query(WorkflowExecutionQueueORM)
            .filter(WorkflowExecutionQueueORM.execution_id == execution_id)
            .first()
        )
        if not row:
            return
        self._set_row_fields(
            row,
            status="done",
            lease_owner=None,
            lease_expire_at=None,
            updated_at=datetime.now(timezone.utc),
        )
        self.db.commit()

    def mark_cancelled(self, execution_id: str) -> None:
        row = (
            self.db.query(WorkflowExecutionQueueORM)
            .filter(WorkflowExecutionQueueORM.execution_id == execution_id)
            .first()
        )
        if not row:
            return
        self._set_row_fields(
            row,
            status="cancelled",
            lease_owner=None,
            lease_expire_at=None,
            updated_at=datetime.now(timezone.utc),
        )
        self.db.commit()

    def lease_next(self, *, lease_owner: str, lease_seconds: int = 30) -> Optional[WorkflowExecutionQueueORM]:
        now = datetime.now(timezone.utc)
        expired_before = now
        row = (
            self.db.query(WorkflowExecutionQueueORM)
            .filter(
                (WorkflowExecutionQueueORM.status == "queued")
                | (
                    (WorkflowExecutionQueueORM.status == "leased")
                    & (WorkflowExecutionQueueORM.lease_expire_at < expired_before)
                )
            )
            .order_by(WorkflowExecutionQueueORM.priority.asc(), WorkflowExecutionQueueORM.queue_order.asc())
            .first()
        )
        if not row:
            return None
        self._set_row_fields(
            row,
            status="leased",
            lease_owner=lease_owner,
            lease_expire_at=now + timedelta(seconds=max(5, int(lease_seconds))),
            updated_at=now,
        )
        self.db.commit()
        self.db.refresh(row)
        return cast(Optional[WorkflowExecutionQueueORM], row)

    def list_active(self) -> List[WorkflowExecutionQueueORM]:
        return cast(
            List[WorkflowExecutionQueueORM],
            (
            self.db.query(WorkflowExecutionQueueORM)
            .filter(WorkflowExecutionQueueORM.status.in_(["queued", "leased"]))
            .order_by(WorkflowExecutionQueueORM.priority.asc(), WorkflowExecutionQueueORM.queue_order.asc())
            .all()
            ),
        )
