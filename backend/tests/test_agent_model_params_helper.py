"""AgentModelParamsJsonMap / agent_model_params_as_dict 契约。"""
from __future__ import annotations

from core.agent_runtime.definition import (
    AgentModelParamsJsonMap,
    agent_model_params_as_dict,
)


def test_agent_model_params_as_dict_none_empty() -> None:
    assert agent_model_params_as_dict(None) == {}


def test_agent_model_params_as_dict_plain_dict_copy() -> None:
    src = {"a": 1, "nested": {"x": 2}}
    out = agent_model_params_as_dict(src)
    assert out == src
    out["a"] = 99
    assert src["a"] == 1


def test_agent_model_params_as_dict_json_map_dump() -> None:
    m = AgentModelParamsJsonMap.model_validate({"intent_rules": [], "k": "v"})
    d = agent_model_params_as_dict(m)
    assert isinstance(d, dict)
    assert d.get("k") == "v"


def test_unknown_type_returns_empty_dict() -> None:
    assert agent_model_params_as_dict("not-a-map") == {}
