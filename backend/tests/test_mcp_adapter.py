"""MCP → SkillDefinition 适配单元测试。"""
import pytest

from core.mcp.adapter import (
    make_mcp_skill_id,
    mcp_tool_dict_to_skill_definition,
    sanitize_segment,
)


def test_sanitize_segment() -> None:
    assert sanitize_segment("a b-c") == "a_b-c"
    assert sanitize_segment("") == "tool"


def test_make_mcp_skill_id_stable() -> None:
    s = make_mcp_skill_id("mcp_srv_abcd1234", "read_file")
    assert "read_file" in s or "read_file"[:8] in s


def test_mcp_tool_dict_to_skill_definition() -> None:
    sd = mcp_tool_dict_to_skill_definition(
        "mcp_srv_test",
        {
            "name": "hello",
            "description": "d",
            "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    )
    assert sd.type == "tool"
    assert sd.definition.get("kind") == "mcp_stdio"
    assert sd.definition.get("tool_name") == "hello"
    assert sd.definition.get("server_config_id") == "mcp_srv_test"
    assert sd.input_schema["type"] == "object"


def test_missing_tool_name_raises() -> None:
    with pytest.raises(ValueError):
        mcp_tool_dict_to_skill_definition("srv", {})
