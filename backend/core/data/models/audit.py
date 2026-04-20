"""
HTTP 审计日志（增强版控制面）
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.data.base import Base


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default", index=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, default="default", index=True)
    platform_role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")

    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
