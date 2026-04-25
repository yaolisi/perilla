"""
多 Agent 协作上下文（Phase 0）：与 agent_runtime / Kernel / Workflow 对齐的埋点。

- 写入 AgentSession.state["collaboration"]，供 Kernel persisted_context 与排障查询。
- 不引入独立业务消息总线；Kernel 仍使用 EventStore 的执行语义事件流。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

# session.state 中协作上下文的键（与方案文档一致）
STATE_KEY_COLLABORATION = "collaboration"


def ensure_correlation_id(value: Optional[str]) -> str:
    """若调用方未提供 correlation_id，则生成可追踪的 id。"""
    s = (value or "").strip()
    if s:
        return s
    return f"corr_{uuid.uuid4().hex[:24]}"


def build_api_root_collaboration(
    agent_id: str,
    *,
    correlation_id: Optional[str] = None,
    orchestrator_agent_id: Optional[str] = None,
    invoked_from: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """直连 POST /api/agents/{id}/run 时根会话的协作上下文。"""
    cid = ensure_correlation_id(correlation_id)
    orch = (orchestrator_agent_id or "").strip() or agent_id
    inv: Dict[str, Any]
    if isinstance(invoked_from, dict) and invoked_from:
        inv = dict(invoked_from)
    else:
        inv = {"type": "api", "agent_id": agent_id}
    return {
        "correlation_id": cid,
        "orchestrator_agent_id": orch,
        "invoked_from": inv,
    }


def build_workflow_collaboration(
    *,
    global_ctx: Dict[str, Any],
    workflow_execution_id: str,
    node_id: str,
    call_chain: List[str],
    agent_id: str,
) -> Dict[str, Any]:
    """Workflow Agent 节点调 AgentRuntime 时的协作上下文。"""
    base = (global_ctx or {}) if isinstance(global_ctx, dict) else {}
    cid = (base.get("correlation_id") or "").strip()
    if not cid and workflow_execution_id:
        cid = f"wfex_{workflow_execution_id}"
    if not cid:
        cid = ensure_correlation_id(None)
    orch = (base.get("orchestrator_agent_id") or "").strip()
    if not orch:
        orch = (call_chain[0] if call_chain else agent_id) or agent_id
    return {
        "correlation_id": cid,
        "orchestrator_agent_id": orch,
        "invoked_from": {
            "type": "workflow",
            "workflow_execution_id": workflow_execution_id,
            "source_node_id": str(node_id),
        },
    }


def merge_collaboration_into_state(state: Optional[Dict[str, Any]], collab: Dict[str, Any]) -> Dict[str, Any]:
    """合并到 session.state（不删除其它 state 键）。"""
    out = dict(state or {})
    out[STATE_KEY_COLLABORATION] = collab
    return out


def get_collaboration_persist_dict(session: Any) -> Dict[str, Any]:
    """
    供 ExecutionKernelAdapter.persisted_context 使用的可 JSON 序列化片段。
    只包含协作相关标量/字典，无 ORM 对象。
    """
    st = getattr(session, "state", None) or {}
    if not isinstance(st, dict):
        return {}
    raw = st.get(STATE_KEY_COLLABORATION)
    if not isinstance(raw, dict) or not raw:
        return {}
    cid = raw.get("correlation_id")
    orch = raw.get("orchestrator_agent_id")
    inv = raw.get("invoked_from")
    out: Dict[str, Any] = {}
    if isinstance(cid, str) and cid.strip():
        out["correlation_id"] = cid.strip()
    if isinstance(orch, str) and orch.strip():
        out["orchestrator_agent_id"] = orch.strip()
    if isinstance(inv, dict) and inv:
        out["invoked_from"] = inv
    return out


def parse_invoked_from_form(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """run/with-files 的表单 JSON 字符串 -> dict。"""
    if not raw or not str(raw).strip():
        return None
    try:
        v = json.loads(str(raw))
        return v if isinstance(v, dict) else None
    except Exception:
        return None
