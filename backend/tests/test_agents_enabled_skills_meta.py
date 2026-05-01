"""
`api.agents._enabled_skills_meta`：与 `enabled_skills` 同序、缺省回退、MCP 标记。

不依赖真实 SkillRegistry 注册数据；通过 monkeypatch 注入 stub。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from api.agents import EnabledSkillMetaItem, _enabled_skills_meta

pytestmark = pytest.mark.no_fallback


class _StubSkill:
    def __init__(self, sid: str) -> None:
        self._sid = sid

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": f"nm-{self._sid}",
            "is_mcp": self._sid.startswith("mcp_"),
        }


class _StubRegistry:
    @classmethod
    def get(cls, skill_id: str, version=None):
        if skill_id == "__missing__":
            return None
        return _StubSkill(skill_id)


@pytest.fixture(autouse=True)
def _patch_skill_registry(monkeypatch):
    monkeypatch.setattr("api.agents.SkillRegistry", _StubRegistry)


def test_meta_matches_enabled_skills_order_and_keys():
    out = _enabled_skills_meta(["first", "__missing__", "mcp_xyz"])
    assert out == [
        EnabledSkillMetaItem(id="first", name="nm-first", is_mcp=False),
        EnabledSkillMetaItem(id="__missing__", name="__missing__", is_mcp=False),
        EnabledSkillMetaItem(id="mcp_xyz", name="nm-mcp_xyz", is_mcp=True),
    ]


def test_meta_empty_when_no_skills():
    assert _enabled_skills_meta([]) == []
