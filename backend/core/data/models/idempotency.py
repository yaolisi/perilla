from sqlalchemy import Column, String, DateTime, Text, UniqueConstraint
from sqlalchemy.sql import func

from core.data.base import Base


class IdempotencyRecordORM(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "scope", "owner_id", "idempotency_key", name="uq_idem_tenant_scope_owner_key"
        ),
    )

    id = Column(String(36), primary_key=True)
    tenant_id = Column(String(128), nullable=False, default="default", index=True)
    scope = Column(String(64), nullable=False, index=True)
    owner_id = Column(String(128), nullable=False, index=True)
    idempotency_key = Column(String(256), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="processing", index=True)
    response_ref = Column(String(128), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    expire_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=func.now(), index=True)
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
