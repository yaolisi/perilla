"""
Kernel 风格上下文（含 tenant_id）经节点 SkillExecutor 调用 MCP Skill 时，
应对持久层按租户解析 MCP server。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from execution_kernel.models.graph_definition import NodeDefinition, NodeType

from core.execution.adapters.node_executors import SkillExecutor as KernelSkillNodeExecutor
from core.skills.models import SkillDefinition
from core.skills.registry import SkillRegistry

pytestmark = pytest.mark.tenant_isolation


@pytest.fixture(autouse=True)
def _clear_skill_registry() -> None:
    SkillRegistry.clear()
    yield
    SkillRegistry.clear()


@pytest.mark.asyncio
async def test_skill_node_mcp_uses_kernel_injected_tenant_id() -> None:
    sid = "kernel.probe.mcp.tenant"
    SkillRegistry.register(
        SkillDefinition(
            id=sid,
            name="probe",
            version="1.0.0",
            description="",
            type="tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            definition={
                "kind": "mcp_stdio",
                "server_config_id": "srv_kernel_mcp",
                "tool_name": "noop",
            },
        )
    )

    node_def = NodeDefinition(
        id="tool_skill",
        type=NodeType.TOOL,
        config={"skill_id": sid, "inputs": {}},
    )

    ctx = {
        "tenant_id": "acme_corp",
        "trace_id": "tr_kernel",
        "agent_id": "agent_1",
        "workspace": ".",
        "permissions": {},
    }

    with patch("core.mcp.persistence.get_mcp_server", return_value=None) as mock_get:
        exec_node = KernelSkillNodeExecutor()
        out = await exec_node.execute(node_def, {}, ctx)

    mock_get.assert_called_once_with("srv_kernel_mcp", tenant_id="acme_corp")
    assert out.get("status") == "error"
    err = out.get("error") or {}
    assert isinstance(err, dict)
    assert "MCP server not found" in str(err.get("message", ""))


@pytest.mark.asyncio
async def test_skill_node_mcp_tenant_from_graph_global_data() -> None:
    """无 context['tenant_id'] 时，回落到 GraphContext.global_data（工作流调度）。"""
    sid = "kernel.probe.mcp.global"
    SkillRegistry.register(
        SkillDefinition(
            id=sid,
            name="probe",
            version="1.0.0",
            description="",
            type="tool",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            definition={
                "kind": "mcp_stdio",
                "server_config_id": "srv_wf_mcp",
                "tool_name": "noop",
            },
        )
    )

    node_def = NodeDefinition(
        id="tool_skill",
        type=NodeType.TOOL,
        config={"skill_id": sid, "inputs": {}},
    )

    class _FakeGC:
        global_data = {"tenant_id": "wf_tenant_9"}

    ctx = {
        "trace_id": "tr_wf",
        "agent_id": "agent_1",
        "workspace": ".",
        "permissions": {},
        "_graph_context": _FakeGC(),
    }

    with patch("core.mcp.persistence.get_mcp_server", return_value=None) as mock_get:
        exec_node = KernelSkillNodeExecutor()
        await exec_node.execute(node_def, {}, ctx)

    mock_get.assert_called_once_with("srv_wf_mcp", tenant_id="wf_tenant_9")
