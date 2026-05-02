"""
MCP Server 配置（stdio 子进程命令，或 Streamable HTTP 远端 URL）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, Index
from sqlalchemy.sql import func

from core.data.base import Base


class McpServer(Base):
    """用户配置的 MCP Server：stdio 命令行，或 HTTP(S) MCP endpoint。"""

    __tablename__ = "mcp_servers"

    id = Column(String, primary_key=True)
    tenant_id = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    # stdio | http
    transport = Column(String(32), nullable=False, server_default="stdio")
    # Streamable HTTP 时的 MCP endpoint（用户显式配置）；stdio 时为 NULL
    base_url = Column(Text)
    # JSON 数组：["npx","-y","@scope/pkg"]；http-only 时可存 []
    command_json = Column(Text, nullable=False)
    env_json = Column(Text)
    cwd = Column(String)
    enabled = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_mcp_servers_tenant_updated", "tenant_id", "updated_at"),)
