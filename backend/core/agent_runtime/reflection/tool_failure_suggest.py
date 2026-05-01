"""
技能 / 工具执行失败后的「仅建议」反思（suggest_only）。

配置（显式开启，默认关闭以控制成本与行为）：
  AgentDefinition.model_params["tool_failure_reflection"] = {
    "enabled": true,
    "mode": "suggest_only"   # 当前仅实现该模式
  }

成功写入 Trace 后，`PlanBasedExecutor` 会打结构化日志事件名 ``tool_failure_reflection_recorded``（含 step_id / agent_id / skill_id / session_id）。
同一次 plan 执行内超过 ``MAX_REFLECTIONS_PER_PLAN_RUN`` 次时跳过推理并打 ``tool_failure_reflection_skipped_limit``。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from log import logger

from core.agent_runtime.definition import AgentDefinition, agent_model_params_as_dict
from core.agent_runtime.session import AgentSession
from core.agent_runtime.v2.models import Step
from core.types import Message

REFLECTION_MAX_INPUT_CHARS = 12000
REFLECTION_MAX_TOKENS = 900
REFLECTION_TEMPERATURE = 0.2
# 同一次 plan 执行（含子计划/重试内）最多触发多少次反思 LLM，防止失败风暴拖垮网关
MAX_REFLECTIONS_PER_PLAN_RUN = 5

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.MULTILINE)


def tool_failure_reflection_enabled(agent: Optional[AgentDefinition]) -> bool:
    """是否启用「工具/技能失败反思」（默认关闭）。"""
    if not agent:
        return False
    mp = agent_model_params_as_dict(getattr(agent, "model_params", None))
    cfg = mp.get("tool_failure_reflection")
    if not isinstance(cfg, dict):
        return False
    if not cfg.get("enabled"):
        return False
    mode = str(cfg.get("mode", "suggest_only") or "suggest_only").strip().lower()
    if mode not in ("suggest_only",):
        logger.warning(
            f"[ToolFailureReflection] Unsupported mode {mode!r}, only 'suggest_only' is implemented"
        )
    return True


def _clip(text: str, max_len: int) -> str:
    if not text or len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n…(truncated)…"


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _build_messages(plan_goal: str, step: Step) -> List[Message]:
    skill_id = (step.inputs or {}).get("skill_id") or ""
    err = step.error or ""
    out = step.outputs
    try:
        out_s = json.dumps(out, ensure_ascii=False, default=str) if out is not None else ""
    except Exception:
        out_s = str(out)
    try:
        inp_s = json.dumps(step.inputs, ensure_ascii=False, default=str) if step.inputs else ""
    except Exception:
        inp_s = str(step.inputs)
    user_block = "\n".join(
        [
            f"## Plan goal\n{_clip(plan_goal, 4000)}",
            f"## skill_id\n{skill_id}",
            f"## step_inputs (JSON)\n{_clip(inp_s, REFLECTION_MAX_INPUT_CHARS)}",
            f"## error_message\n{_clip(err, 4000)}",
            f"## step_outputs (JSON)\n{_clip(out_s, REFLECTION_MAX_INPUT_CHARS)}",
        ]
    )
    sys_text = (
        "You analyze failed tool/skill invocations. Rules:\n"
        "- Do not claim you executed or fixed anything.\n"
        "- Suggestions are advisory; the user or another system may apply them.\n"
        "- Respond with a single JSON object only, no other text, with keys:\n"
        '  "error_category" (string, e.g. parameter_validation, permission, tool_unavailable, logic),\n'
        '  "likely_cause" (string, concise),\n'
        '  "suggested_next_steps" (array of strings, concrete and ordered),\n'
        '  "parameter_hints" (object or null: suggested key/value fixes, still advisory),\n'
        '  "notes" (string, optional caveats).\n'
    )
    return [
        Message(role="system", content=sys_text),
        Message(role="user", content=user_block),
    ]


async def run_tool_failure_suggestion(
    *,
    agent: AgentDefinition,
    session: Optional[AgentSession],
    step: Step,
    plan_goal: str,
) -> Optional[Dict[str, Any]]:
    """
    调用本 Agent 的 model_id 生成失败诊断建议。失败时返回 None，不抛给上层。
    """
    from core.inference import get_inference_client

    if not tool_failure_reflection_enabled(agent):
        return None

    messages = _build_messages(plan_goal, step)
    client = get_inference_client()
    meta = {
        "caller": "ToolFailureReflection",
        "agent_id": agent.agent_id,
    }
    if session is not None and getattr(session, "session_id", None):
        meta["session_id"] = session.session_id

    try:
        resp = await client.generate(
            model=agent.model_id,
            messages=messages,
            temperature=REFLECTION_TEMPERATURE,
            max_tokens=REFLECTION_MAX_TOKENS,
            metadata=meta,
        )
    except Exception as e:
        logger.warning(f"[ToolFailureReflection] inference failed: {e}")
        return None

    text = (resp.text or "").strip()
    parsed = _parse_json_object(text)
    if not isinstance(parsed, dict):
        logger.warning("[ToolFailureReflection] Could not parse JSON from model output")
        return {
            "mode": "suggest_only",
            "parse_error": True,
            "raw_text_excerpt": _clip(text, 2000),
        }

    return {
        "mode": "suggest_only",
        "error_category": parsed.get("error_category"),
        "likely_cause": parsed.get("likely_cause"),
        "suggested_next_steps": _as_str_list(parsed.get("suggested_next_steps")),
        "parameter_hints": parsed.get("parameter_hints"),
        "notes": parsed.get("notes"),
    }


def _as_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        out: List[str] = []
        for x in v:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
        return out
    return []
