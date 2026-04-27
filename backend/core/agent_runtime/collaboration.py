"""
多 Agent 协作上下文（Phase 0）：与 agent_runtime / Kernel / Workflow 对齐的埋点。

- 写入 AgentSession.state["collaboration"]，供 Kernel persisted_context 与排障查询。
- 不引入独立业务消息总线；Kernel 仍使用 EventStore 的执行语义事件流。
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

# session.state 中协作上下文的键（与方案文档一致）
STATE_KEY_COLLABORATION = "collaboration"
STATE_KEY_COLLABORATION_MESSAGES = "messages"
DEFAULT_COLLABORATION_MESSAGE_STATUS = "sent"
COLLABORATION_MESSAGE_ALLOWED_STATUS = {
    "queued",
    "sent",
    "received",
    "running",
    "success",
    "error",
    "retry",
}


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


def build_collaboration_message(
    payload: Dict[str, Any],
    *,
    default_status: str = DEFAULT_COLLABORATION_MESSAGE_STATUS,
) -> Dict[str, Any]:
    """
    归一化协作消息，保证最小协议字段齐全：
    sender / receiver / task_id / content / timestamp / status。
    """
    src = dict(payload or {})
    sender = str(src.get("sender") or "").strip()
    receiver = str(src.get("receiver") or "").strip()
    task_id = str(src.get("task_id") or "").strip()
    if not sender or not receiver or not task_id:
        raise ValueError("sender/receiver/task_id are required")
    content = src.get("content")
    if not isinstance(content, dict):
        raise ValueError("content must be object")

    status = str(src.get("status") or default_status).strip().lower()
    if status not in COLLABORATION_MESSAGE_ALLOWED_STATUS:
        raise ValueError("status is invalid")

    timestamp = src.get("timestamp")
    if isinstance(timestamp, str) and timestamp.strip():
        ts = timestamp.strip()
    else:
        ts = datetime.now(UTC).isoformat()

    normalized: Dict[str, Any] = {
        "message_id": str(src.get("message_id") or f"cmsg_{uuid.uuid4().hex[:16]}"),
        "sender": sender,
        "receiver": receiver,
        "task_id": task_id,
        "content": content,
        "timestamp": ts,
        "status": status,
    }
    if src.get("meta") is not None:
        normalized["meta"] = src.get("meta")
    return normalized


def append_collaboration_message_to_state(
    state: Optional[Dict[str, Any]],
    message: Dict[str, Any],
    *,
    max_messages: int = 500,
) -> Dict[str, Any]:
    """将消息追加到 state.collaboration.messages，保留最近 max_messages 条。"""
    out = dict(state or {})
    collab = dict(out.get(STATE_KEY_COLLABORATION) or {})
    current = collab.get(STATE_KEY_COLLABORATION_MESSAGES)
    messages = list(current) if isinstance(current, list) else []
    messages.append(dict(message))
    if max_messages > 0 and len(messages) > max_messages:
        messages = messages[-max_messages:]
    collab[STATE_KEY_COLLABORATION_MESSAGES] = messages
    out[STATE_KEY_COLLABORATION] = collab
    return out
