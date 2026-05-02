"""MCP stdio skill 执行时按 tenant_id 解析 server 配置。"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.data.base import Base
from core.data.models.mcp_server import McpServer

from core.skills.contract import SkillExecutionRequest, ExecutionMetrics
from core.skills.executor import DefaultSkillExecutor
from core.skills.models import SkillDefinition

pytestmark = pytest.mark.tenant_isolation


def _mcp_tool_definition() -> SkillDefinition:
    return SkillDefinition(
        id="mcp.tenant_test",
        name="t",
        version="1.0.0",
        description="",
        type="tool",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        definition={
            "kind": "mcp_stdio",
            "server_config_id": "srv_cfg_1",
            "tool_name": "noop",
        },
    )


@pytest.mark.asyncio
async def test_mcp_stdio_calls_get_mcp_server_with_tenant_when_set() -> None:
    definition = _mcp_tool_definition()
    req = SkillExecutionRequest(
        skill_id=definition.id,
        input={},
        trace_id="tr",
        caller_id="c",
        tenant_id="acme",
    )
    metrics = ExecutionMetrics()
    with patch("core.mcp.persistence.get_mcp_server", return_value=None) as mock_get:
        ex = DefaultSkillExecutor()
        out = await ex._execute_mcp_stdio(definition, req, metrics)
    mock_get.assert_called_once_with("srv_cfg_1", tenant_id="acme")
    assert out.get("error") == "MCP server not found: srv_cfg_1"


@pytest.mark.asyncio
async def test_mcp_stdio_blocked_emits_structured_audit() -> None:
    definition = _mcp_tool_definition()
    req = SkillExecutionRequest(
        skill_id=definition.id,
        input={},
        trace_id="tr_audit",
        caller_id="caller_x",
        tenant_id="acme",
    )
    metrics = ExecutionMetrics()
    with patch("core.mcp.persistence.get_mcp_server", return_value=None):
        with patch("core.skills.executor.log_structured") as mock_ls:
            ex = DefaultSkillExecutor()
            await ex._execute_mcp_stdio(definition, req, metrics)
    mock_ls.assert_called_once()
    args, kwargs = mock_ls.call_args
    assert args[0] == "Skills"
    assert args[1] == "mcp_skill_invoke_blocked"
    assert kwargs["reason"] == "mcp_server_not_found"
    assert kwargs["tenant_id"] == "acme"
    assert kwargs["server_config_id"] == "srv_cfg_1"


@pytest.mark.asyncio
async def test_mcp_stdio_uses_default_tenant_when_request_tenant_missing() -> None:
    """缺省 tenant 时按 default 命名空间查库，不得退化为无租户查询（防跨租户误匹配）。"""
    definition = _mcp_tool_definition()
    req = SkillExecutionRequest(
        skill_id=definition.id,
        input={},
        trace_id="tr",
        caller_id="c",
        tenant_id=None,
    )
    metrics = ExecutionMetrics()
    with patch("core.mcp.persistence.get_mcp_server", return_value=None) as mock_get:
        ex = DefaultSkillExecutor()
        await ex._execute_mcp_stdio(definition, req, metrics)
    mock_get.assert_called_once_with("srv_cfg_1", tenant_id="default")


def test_get_mcp_server_filters_wrong_tenant(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一 server id，不同 tenant 行应隔离；省略 tenant 时仅解析 default 命名空间。"""
    db_file = tmp_path / "mcp_tenant.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine, tables=[McpServer.__table__])

    SessionLocalTest = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    @contextmanager
    def test_db_session(retry_count: int = 3, retry_delay: float = 0.1):
        _ = (retry_count, retry_delay)
        db = SessionLocalTest()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr("core.mcp.persistence.db_session", test_db_session)

    from core.mcp.persistence import create_mcp_server, get_mcp_server

    create_mcp_server(name="n", command=["true"], server_id="srv_shared", tenant_id="tenant_a")
    create_mcp_server(name="n_def", command=["true"], server_id="srv_in_default", tenant_id="default")

    assert get_mcp_server("srv_shared", tenant_id="tenant_a") is not None
    assert get_mcp_server("srv_shared", tenant_id="tenant_b") is None
    assert get_mcp_server("srv_shared") is None
    assert get_mcp_server("srv_in_default") is not None
    assert get_mcp_server("srv_in_default", tenant_id=None) is not None
