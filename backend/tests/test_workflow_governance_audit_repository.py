from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.workflows.repository.workflow_governance_audit_repository import WorkflowGovernanceAuditRepository


def _make_session_factory(tmp_path):
    db_file = tmp_path / "gov_audit_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_create_audit_default_tenant(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    with session_factory() as db:
        repo = WorkflowGovernanceAuditRepository(db)
        row = repo.create_audit(
            "wf_1",
            "alice",
            {"max_queue_size": 1},
            {"max_queue_size": 2},
        )
        assert row["workflow_id"] == "wf_1"
        listed = repo.list_audits("wf_1", tenant_id="default")
        assert len(listed) == 1


def test_list_audits_filters_by_tenant(tmp_path):
    session_factory = _make_session_factory(tmp_path)
    wf_id = "wf_shared_id"
    with session_factory() as db:
        repo = WorkflowGovernanceAuditRepository(db)
        repo.create_audit(wf_id, "u", {"a": 1}, {"a": 2}, tenant_id="tenant_a")
        repo.create_audit(wf_id, "u", {"a": 2}, {"a": 3}, tenant_id="tenant_b")

        a_only = repo.list_audits(wf_id, tenant_id="tenant_a")
        assert len(a_only) == 1
        assert a_only[0]["old_config"] == {"a": 1}

        b_only = repo.count_audits(wf_id, tenant_id="tenant_b")
        assert b_only == 1

        default_empty = repo.list_audits(wf_id, tenant_id="default")
        assert len(default_empty) == 0
