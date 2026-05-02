"""
插件市场 ORM 模型。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.sql import func

from core.data.base import Base


class PluginPackageORM(Base):
    __tablename__ = "plugin_packages"

    id = Column(String(128), primary_key=True)
    name = Column(String(256), nullable=False, index=True)
    version = Column(String(64), nullable=False, index=True)
    manifest_path = Column(Text, nullable=False)
    package_path = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    author = Column(String(256), nullable=True)
    source = Column(String(64), nullable=False, default="third_party")
    review_status = Column(String(32), nullable=False, default="pending")
    visibility = Column(String(32), nullable=False, default="private")
    signature = Column(Text, nullable=True)
    signature_digest = Column(String(128), nullable=True)
    compatible_gateway_versions = Column(Text, nullable=True)
    permissions_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PluginInstallationORM(Base):
    __tablename__ = "plugin_installations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "package_id", name="uq_plugin_installations_tenant_package"),
        Index("idx_plugin_installations_tenant_updated", "tenant_id", "updated_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(128), nullable=False, default="default", index=True)
    package_id = Column(String(128), nullable=False, index=True)
    name = Column(String(256), nullable=False, index=True)
    version = Column(String(64), nullable=False, index=True)
    manifest_path = Column(Text, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    installed_by = Column(String(128), nullable=True)
    installed_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
