"""协作上下文：build/merge 与 Kernel 持久化片段。"""
from __future__ import annotations

import pytest

from core.agent_runtime.collaboration import (
    STATE_KEY_COLLABORATION,
    build_api_root_collaboration,
    build_workflow_collaboration,
    get_collaboration_persist_dict,
    merge_collaboration_into_state,
    parse_invoked_from_form,
)
from core.agent_runtime.session import AgentSession


def test_build_api_root_defaults():
    c = build_api_root_collaboration("agent_a")
    assert c["orchestrator_agent_id"] == "agent_a"
    assert c["correlation_id"].startswith("corr_")
    assert c["invoked_from"]["type"] == "api"
    assert c["invoked_from"]["agent_id"] == "agent_a"


def test_build_api_root_custom():
    c = build_api_root_collaboration(
        "agent_a",
        correlation_id="my-corr",
        orchestrator_agent_id="root",
        invoked_from={"type": "test", "x": 1},
    )
    assert c["correlation_id"] == "my-corr"
    assert c["orchestrator_agent_id"] == "root"
    assert c["invoked_from"]["type"] == "test"


def test_workflow_collaboration():
    gc = {"correlation_id": "wfex_1", "orchestrator_agent_id": "orch"}
    c = build_workflow_collaboration(
        global_ctx=gc,
        workflow_execution_id="ex1",
        node_id="n1",
        call_chain=[],
        agent_id="sub",
    )
    assert c["correlation_id"] == "wfex_1"
    assert c["orchestrator_agent_id"] == "orch"
    assert c["invoked_from"]["type"] == "workflow"
    assert c["invoked_from"]["workflow_execution_id"] == "ex1"


def test_workflow_collaboration_fills_correlation_from_execution():
    c = build_workflow_collaboration(
        global_ctx={},
        workflow_execution_id="ex9",
        node_id="n1",
        call_chain=[],
        agent_id="a",
    )
    assert c["correlation_id"] == "wfex_ex9"


def test_workflow_bootstrap_persisted_global_context_merge():
    """
    与 workflow_runtime._bootstrap_scheduler_instance 中
    update_global_context 的合并方式一致：保留用户 global_context 并写入归一化 correlation_id。
    """
    execution_id = "ex-abc"
    user_gc = {"trace_id": "t1", "other": 1}
    base_gc = dict(user_gc)
    if not str(base_gc.get("correlation_id") or "").strip():
        base_gc["correlation_id"] = f"wfex_{execution_id}"
    global_context = {**base_gc, "execution_id": execution_id}  # 调度侧还会带更多键
    cid = global_context["correlation_id"]
    persisted_gc = {**user_gc, "correlation_id": cid}
    assert persisted_gc == {"trace_id": "t1", "other": 1, "correlation_id": f"wfex_{execution_id}"}


def test_workflow_bootstrap_persist_keeps_user_correlation_id():
    user_gc = {"correlation_id": "user-corr-1", "trace_id": "t2"}
    base_gc = dict(user_gc)
    if not str(base_gc.get("correlation_id") or "").strip():
        base_gc["correlation_id"] = "should_not_apply"
    assert base_gc["correlation_id"] == "user-corr-1"
    global_context = {**base_gc, "execution_id": "ex"}
    persisted_gc = {**user_gc, "correlation_id": global_context["correlation_id"]}
    assert persisted_gc["correlation_id"] == "user-corr-1"


def test_workflow_persist_orchestrator_merges_with_existing_global_context():
    cur_gc = {"correlation_id": "wfex_ex1", "trace_id": "t3"}
    orch = "agent_root"
    merged = {**cur_gc, "orchestrator_agent_id": orch}
    assert merged["correlation_id"] == "wfex_ex1"
    assert merged["orchestrator_agent_id"] == "agent_root"


def test_collaboration_list_filter_by_orchestrator():
    """与 /api/collaboration/.../correlation?orchestrator_agent_id= 的筛选一致。"""
    from core.agent_runtime.collaboration import STATE_KEY_COLLABORATION

    cid = "wfex_1"
    orch_filter = "a1"
    rows: list[dict] = [
        {STATE_KEY_COLLABORATION: {"correlation_id": cid, "orchestrator_agent_id": "a1", "invoked_from": {}}},
        {STATE_KEY_COLLABORATION: {"correlation_id": cid, "orchestrator_agent_id": "a2", "invoked_from": {}}},
    ]
    out = []
    for st in rows:
        block = st.get(STATE_KEY_COLLABORATION)
        if (block.get("correlation_id") or "").strip() != cid:
            continue
        if (block.get("orchestrator_agent_id") or "").strip() != orch_filter:
            continue
        out.append(st)
    assert len(out) == 1


def test_persist_dict_from_session():
    s = AgentSession(
        session_id="s1",
        agent_id="a1",
        state={STATE_KEY_COLLABORATION: {"correlation_id": "c1", "orchestrator_agent_id": "o1", "invoked_from": {"type": "api"}}},
    )
    p = get_collaboration_persist_dict(s)
    assert p["correlation_id"] == "c1"
    assert p["orchestrator_agent_id"] == "o1"


def test_parse_invoked_from_form():
    assert parse_invoked_from_form('{"type":"x"}') == {"type": "x"}
    assert parse_invoked_from_form(None) is None
    assert parse_invoked_from_form("not-json") is None


def test_merge_preserves_other_state():
    m = merge_collaboration_into_state({"k": 1}, {"correlation_id": "x", "orchestrator_agent_id": "y", "invoked_from": {}})
    assert m["k"] == 1
    assert m[STATE_KEY_COLLABORATION]["correlation_id"] == "x"
