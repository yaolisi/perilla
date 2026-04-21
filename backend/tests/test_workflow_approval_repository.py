from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.workflows.repository.workflow_approval_task_repository import WorkflowApprovalTaskRepository


def _make_session_factory(tmp_path):
    db_file = tmp_path / "approval_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_create_and_approve_task(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowApprovalTaskRepository(db)
        task = repo.create_task(
            execution_id="exec_1",
            workflow_id="wf_1",
            node_id="approve_1",
            title="Need approval",
            reason="dangerous operation",
            payload={"x": 1},
            requested_by="u1",
        )
        assert task.status == "pending"
        approved = repo.decide(task_id=task.id, decision="approved", decided_by="admin")
        assert approved is not None
        assert approved.status == "approved"
        assert approved.decided_by == "admin"


def test_expire_pending_task(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowApprovalTaskRepository(db)
        task = repo.create_task(
            execution_id="exec_2",
            workflow_id="wf_1",
            node_id="approve_2",
            title="Need approval",
            reason="timeout check",
            payload={},
            requested_by="u1",
            expires_in_seconds=1,
        )
        row = repo.get_by_id(task.id)
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.commit()

        expired = repo.expire_pending_tasks("exec_2")
        assert expired == 1
        row = repo.get_by_id(task.id)
        assert row is not None
        assert row.status == "expired"
