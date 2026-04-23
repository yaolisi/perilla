from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.data.models.idempotency import IdempotencyRecordORM

IDEMPOTENCY_STATUS_PROCESSING: Literal["processing"] = "processing"
IDEMPOTENCY_STATUS_SUCCEEDED: Literal["succeeded"] = "succeeded"
IDEMPOTENCY_STATUS_FAILED: Literal["failed"] = "failed"


@dataclass
class IdempotencyClaimResult:
    record: IdempotencyRecordORM
    is_new: bool
    conflict: bool


class IdempotencyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_existing(self, scope: str, owner_id: str, key: str) -> Optional[IdempotencyRecordORM]:
        return cast(
            Optional[IdempotencyRecordORM],
            (
            self.db.query(IdempotencyRecordORM)
            .filter(IdempotencyRecordORM.scope == scope)
            .filter(IdempotencyRecordORM.owner_id == owner_id)
            .filter(IdempotencyRecordORM.idempotency_key == key)
            .first()
            ),
        )

    def _get_by_id(self, record_id: str) -> Optional[IdempotencyRecordORM]:
        return cast(
            Optional[IdempotencyRecordORM],
            self.db.query(IdempotencyRecordORM)
            .filter(IdempotencyRecordORM.id == record_id)
            .first(),
        )

    def claim(
        self,
        *,
        scope: str,
        owner_id: str,
        key: str,
        request_hash: str,
        ttl_seconds: int = 86400,
    ) -> IdempotencyClaimResult:
        existing = self._get_existing(scope=scope, owner_id=owner_id, key=key)
        if existing:
            conflict = existing.request_hash != request_hash
            return IdempotencyClaimResult(record=existing, is_new=False, conflict=conflict)

        expire_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(ttl_seconds)))
        row = IdempotencyRecordORM(
            id=str(uuid.uuid4()),
            scope=scope,
            owner_id=owner_id,
            idempotency_key=key,
            request_hash=request_hash,
            status=IDEMPOTENCY_STATUS_PROCESSING,
            expire_at=expire_at,
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._get_existing(scope=scope, owner_id=owner_id, key=key)
            if not existing:
                raise
            conflict = existing.request_hash != request_hash
            return IdempotencyClaimResult(record=existing, is_new=False, conflict=conflict)
        self.db.refresh(row)
        return IdempotencyClaimResult(record=row, is_new=True, conflict=False)

    def mark_succeeded(self, *, record_id: str, response_ref: str) -> None:
        row = self._get_by_id(record_id)
        if not row:
            return
        row.status = IDEMPOTENCY_STATUS_SUCCEEDED
        row.response_ref = response_ref
        row.error_message = None
        self.db.commit()

    def mark_failed(self, *, record_id: str, error_message: str) -> None:
        row = self._get_by_id(record_id)
        if not row:
            return
        row.status = IDEMPOTENCY_STATUS_FAILED
        row.error_message = (error_message or "")[:2000]
        self.db.commit()
