"""
Workflow Governance Audit Repository (ORM)
"""

from typing import Any, Dict, List, Optional, cast
from datetime import UTC, datetime
import uuid
from sqlalchemy.orm import Session

from core.data.models.workflow import WorkflowGovernanceAuditORM


class WorkflowGovernanceAuditRepository:
    """治理配置变更审计仓库"""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _filter_tenant(q, tenant_id: Optional[str]):
        if tenant_id is None:
            return q
        tid = (str(tenant_id).strip() or "default")
        return q.filter(WorkflowGovernanceAuditORM.tenant_id == tid)

    def create_audit(
        self,
        workflow_id: str,
        changed_by: Optional[str],
        old_config: Dict[str, Any],
        new_config: Dict[str, Any],
        *,
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        tid = (str(tenant_id).strip() or "default")
        row = WorkflowGovernanceAuditORM(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            workflow_id=workflow_id,
            changed_by=changed_by,
            old_config=old_config or {},
            new_config=new_config or {},
            created_at=datetime.now(UTC),
        )
        self.db.add(row)
        self.db.commit()
        return {
            "id": row.id,
            "workflow_id": row.workflow_id,
            "changed_by": row.changed_by,
            "old_config": row.old_config or {},
            "new_config": row.new_config or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def list_audits(
        self,
        workflow_id: str,
        limit: int = 50,
        offset: int = 0,
        *,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        q = self.db.query(WorkflowGovernanceAuditORM).filter(
            WorkflowGovernanceAuditORM.workflow_id == workflow_id
        )
        q = self._filter_tenant(q, tenant_id)
        rows = (
            q.order_by(WorkflowGovernanceAuditORM.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [
            {
                "id": r.id,
                "workflow_id": r.workflow_id,
                "changed_by": r.changed_by,
                "old_config": r.old_config or {},
                "new_config": r.new_config or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def count_audits(self, workflow_id: str, *, tenant_id: Optional[str] = None) -> int:
        q = self.db.query(WorkflowGovernanceAuditORM).filter(
            WorkflowGovernanceAuditORM.workflow_id == workflow_id
        )
        q = self._filter_tenant(q, tenant_id)
        return cast(int, q.count())
