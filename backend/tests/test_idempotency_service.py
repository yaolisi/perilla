from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.data.models.idempotency import IdempotencyRecordORM
from core.idempotency.service import IdempotencyService


def _make_session(tmp_path):
    db_file = tmp_path / "idempotency_service.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def test_claim_creates_record_and_second_claim_reuses_existing(tmp_path):
    db = _make_session(tmp_path)
    service = IdempotencyService(db)

    first = service.claim(
        scope="workflow",
        owner_id="u1",
        key="idem-key-1",
        request_hash="hash-a",
    )
    second = service.claim(
        scope="workflow",
        owner_id="u1",
        key="idem-key-1",
        request_hash="hash-a",
    )

    assert first.is_new is True
    assert first.conflict is False
    assert second.is_new is False
    assert second.conflict is False
    assert second.record.id == first.record.id


def test_claim_conflict_and_mark_failed_truncates_message(tmp_path):
    db = _make_session(tmp_path)
    service = IdempotencyService(db)

    claimed = service.claim(
        scope="workflow",
        owner_id="u1",
        key="idem-key-2",
        request_hash="hash-a",
    )
    conflict = service.claim(
        scope="workflow",
        owner_id="u1",
        key="idem-key-2",
        request_hash="hash-b",
    )
    assert conflict.is_new is False
    assert conflict.conflict is True

    service.mark_succeeded(record_id=claimed.record.id, response_ref="resp_1")
    row = db.query(IdempotencyRecordORM).filter(IdempotencyRecordORM.id == claimed.record.id).first()
    assert row is not None
    assert row.status == "succeeded"
    assert row.response_ref == "resp_1"

    oversized = "x" * 2505
    service.mark_failed(record_id=claimed.record.id, error_message=oversized)
    row2 = db.query(IdempotencyRecordORM).filter(IdempotencyRecordORM.id == claimed.record.id).first()
    assert row2 is not None
    assert row2.status == "failed"
    assert row2.error_message is not None
    assert len(row2.error_message) == 2000
