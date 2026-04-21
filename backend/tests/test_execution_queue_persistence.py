from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.data.models.workflow import WorkflowExecutionQueueORM
from core.workflows.repository.workflow_execution_queue_repository import (
    WorkflowExecutionQueueRepository,
)


def _make_session_factory(tmp_path):
    db_file = tmp_path / "queue_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_queue_repository_lease_and_done(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowExecutionQueueRepository(db)
        repo.enqueue(
            execution_id="exec_1",
            workflow_id="wf_1",
            version_id="v1",
            priority=1,
            queue_order=1,
        )

        leased = repo.lease_next(lease_owner="owner_1", lease_seconds=30)
        assert leased is not None
        assert leased.execution_id == "exec_1"
        assert leased.status == "leased"
        assert leased.lease_owner == "owner_1"

        repo.mark_done("exec_1")
        row = db.query(WorkflowExecutionQueueORM).filter_by(execution_id="exec_1").first()
        assert row is not None
        assert row.status == "done"


def test_queue_repository_expired_lease_can_be_released_again(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowExecutionQueueRepository(db)
        repo.enqueue(
            execution_id="exec_2",
            workflow_id="wf_1",
            version_id="v1",
            priority=1,
            queue_order=1,
        )
        leased = repo.lease_next(lease_owner="owner_1", lease_seconds=1)
        assert leased is not None

        row = db.query(WorkflowExecutionQueueORM).filter_by(execution_id="exec_2").first()
        row.lease_expire_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()

        leased_again = repo.lease_next(lease_owner="owner_2", lease_seconds=30)
        assert leased_again is not None
        assert leased_again.execution_id == "exec_2"
        assert leased_again.lease_owner == "owner_2"


def test_execution_manager_recovers_persisted_queue(tmp_path, monkeypatch):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowExecutionQueueRepository(db)
        repo.enqueue(
            execution_id="exec_recover",
            workflow_id="wf_recover",
            version_id="v1",
            priority=2,
            queue_order=10,
        )

    import core.workflows.governance.execution_manager as em_mod

    monkeypatch.setattr(em_mod, "SessionLocal", session_factory)
    manager = em_mod.ExecutionManager(global_concurrency_limit=1, per_workflow_concurrency_limit=1)

    assert "exec_recover" in manager._queued_executions
    assert manager._queued_by_workflow.get("wf_recover") == 1


def test_queue_repository_cancel_is_idempotent(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowExecutionQueueRepository(db)
        repo.enqueue(
            execution_id="exec_cancel",
            workflow_id="wf_1",
            version_id="v1",
            priority=1,
            queue_order=1,
        )
        repo.mark_cancelled("exec_cancel")
        repo.mark_cancelled("exec_cancel")

        row = db.query(WorkflowExecutionQueueORM).filter_by(execution_id="exec_cancel").first()
        assert row is not None
        assert row.status == "cancelled"
