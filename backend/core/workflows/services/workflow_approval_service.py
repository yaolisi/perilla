from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from core.data.base import sessionmaker_for_engine
from core.data.models.workflow import WorkflowApprovalTaskORM
from core.workflows.governance import get_execution_manager
from core.workflows.models import WorkflowExecutionState
from core.workflows.repository import WorkflowApprovalTaskRepository
from core.workflows.runtime import WorkflowRuntime
from core.workflows.services.workflow_execution_service import WorkflowExecutionService


@dataclass
class ApprovalDecisionResult:
    task: Optional[WorkflowApprovalTaskORM]
    expired: bool = False


class WorkflowApprovalService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = WorkflowApprovalTaskRepository(db)
        self.execution_service = WorkflowExecutionService(db)

    @staticmethod
    def _api_tenant(tenant_id: Optional[str]) -> Optional[str]:
        if tenant_id is None:
            return None
        return (str(tenant_id).strip() or "default")

    def list_for_execution(self, execution_id: str, tenant_id: Optional[str] = None) -> List[WorkflowApprovalTaskORM]:
        eff = self._api_tenant(tenant_id)
        self.repo.expire_pending_tasks(execution_id, eff)
        return self.repo.list_by_execution(execution_id, eff)

    def approve(
        self, *, execution_id: str, task_id: str, decided_by: str, tenant_id: Optional[str] = None
    ) -> ApprovalDecisionResult:
        eff = self._api_tenant(tenant_id)
        task = self.repo.get_by_id(task_id, eff)
        if not task or task.execution_id != execution_id:
            return ApprovalDecisionResult(task=None, expired=False)

        row_tid = (str(getattr(task, "tenant_id", None) or "").strip() or "default")

        self.repo.expire_pending_tasks(execution_id, eff)
        task = self.repo.get_by_id(task_id, eff)
        if task and task.status == "expired":
            self.execution_service.repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=f"Approval expired for node {task.node_id}",
                error_details={"code": "WORKFLOW_APPROVAL_EXPIRED", "task_id": task.id},
                tenant_id=row_tid,
            )
            return ApprovalDecisionResult(task=task, expired=True)

        task = self.repo.decide(task_id=task_id, decision="approved", decided_by=decided_by, tenant_id=eff)
        if task is None:
            return ApprovalDecisionResult(task=None, expired=False)
        execution = self.execution_service.get_execution(execution_id, tenant_id=eff)
        if execution is None:
            return ApprovalDecisionResult(task=task, expired=False)

        global_ctx = dict(execution.global_context or {})
        decisions = dict(global_ctx.get("approval_decisions") or {})
        decisions[task.node_id] = "approved"
        global_ctx["approval_decisions"] = decisions
        self.execution_service.repository.update_global_context(execution_id, global_ctx, tenant_id=row_tid)

        if not self.repo.list_pending_by_execution(execution_id, eff):
            self.execution_service.repository.update_state(
                execution_id, WorkflowExecutionState.PENDING, tenant_id=row_tid
            )
            db_bg = sessionmaker_for_engine(self.db.get_bind())()

            async def _resume() -> None:
                try:
                    execution_bg = WorkflowExecutionService(db_bg).get_execution(execution_id, tenant_id=eff)
                    if not execution_bg:
                        return
                    runtime_bg = WorkflowRuntime(db_bg, get_execution_manager())
                    await runtime_bg.execute(execution_bg, wait_for_completion=False)
                finally:
                    db_bg.close()

            _resume_task = asyncio.create_task(_resume())
            _ = _resume_task

        return ApprovalDecisionResult(task=task, expired=False)

    def reject(
        self, *, execution_id: str, task_id: str, decided_by: str, tenant_id: Optional[str] = None
    ) -> ApprovalDecisionResult:
        eff = self._api_tenant(tenant_id)
        task = self.repo.get_by_id(task_id, eff)
        if not task or task.execution_id != execution_id:
            return ApprovalDecisionResult(task=None, expired=False)

        row_tid = (str(getattr(task, "tenant_id", None) or "").strip() or "default")

        self.repo.expire_pending_tasks(execution_id, eff)
        task = self.repo.get_by_id(task_id, eff)
        if task and task.status == "expired":
            self.execution_service.repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=f"Approval expired for node {task.node_id}",
                error_details={"code": "WORKFLOW_APPROVAL_EXPIRED", "task_id": task.id},
                tenant_id=row_tid,
            )
            return ApprovalDecisionResult(task=task, expired=True)

        task = self.repo.decide(task_id=task_id, decision="rejected", decided_by=decided_by, tenant_id=eff)
        if task is None:
            return ApprovalDecisionResult(task=None, expired=False)
        execution = self.execution_service.get_execution(execution_id, tenant_id=eff)
        if execution is not None:
            global_ctx = dict(execution.global_context or {})
            decisions = dict(global_ctx.get("approval_decisions") or {})
            decisions[task.node_id] = "rejected"
            global_ctx["approval_decisions"] = decisions
            self.execution_service.repository.update_global_context(execution_id, global_ctx, tenant_id=row_tid)
            self.execution_service.repository.update_state(
                execution_id,
                WorkflowExecutionState.FAILED,
                error_message=f"Approval rejected for node {task.node_id}",
                error_details={"code": "WORKFLOW_APPROVAL_REJECTED", "task_id": task.id},
                tenant_id=row_tid,
            )

        return ApprovalDecisionResult(task=task, expired=False)
