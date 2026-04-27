"""
Workflow 工具组合推荐（协同过滤增强版）

评分综合以下信号：
1) 当前工具集合与模板工具集合重叠度
2) 用户/全局模板使用频次
3) 工具转移概率（A -> B）协同信号
4) 冷启动先验（低数据量场景保持稳定推荐）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from core.system.settings_store import get_system_settings_store

USAGE_STORE_KEY = "workflow_tool_composition_usage_v1"


@dataclass(frozen=True)
class ToolCompositionTemplate:
    template_id: str
    name: str
    description: str
    tools: List[str]


TEMPLATES: List[ToolCompositionTemplate] = [
    ToolCompositionTemplate(
        template_id="travel_planning",
        name="差旅规划模板",
        description="天气查询 -> 机票预订 -> 酒店推荐（含天气分支）",
        tools=["weather.query", "flight.booking", "hotel.recommendation"],
    ),
    ToolCompositionTemplate(
        template_id="market_research",
        name="市场调研模板",
        description="搜索采集 -> 摘要分析 -> 报告输出",
        tools=["web.search", "llm.analyze", "report.export"],
    ),
]


class WorkflowToolCompositionRecommender:
    def __init__(self) -> None:
        self._settings = get_system_settings_store()

    def record_usage(
        self,
        *,
        workflow_id: str,
        user_id: str,
        template_id: str,
        tool_sequence: List[str],
    ) -> None:
        payload = self._read_payload()
        payload.setdefault("global_template_uses", {})
        payload.setdefault("user_template_uses", {})
        payload.setdefault("user_tool_sequences", {})
        payload.setdefault("global_tool_transitions", {})
        payload.setdefault("user_tool_transitions", {})

        payload["global_template_uses"][template_id] = int(
            payload["global_template_uses"].get(template_id, 0)
        ) + 1

        user_tpl = payload["user_template_uses"].setdefault(user_id, {})
        user_tpl[template_id] = int(user_tpl.get(template_id, 0)) + 1

        if tool_sequence:
            normalized_seq = [str(x).strip() for x in tool_sequence if str(x).strip()]
            user_seqs = payload["user_tool_sequences"].setdefault(user_id, [])
            user_seqs.append(
                {
                    "workflow_id": workflow_id,
                    "tools": normalized_seq,
                }
            )
            if len(user_seqs) > 200:
                payload["user_tool_sequences"][user_id] = user_seqs[-200:]
            self._accumulate_transitions(payload, user_id=user_id, tools=normalized_seq)

        self._settings.set_setting(USAGE_STORE_KEY, payload)

    def record_runtime_sequence(
        self,
        *,
        workflow_id: str,
        user_id: str,
        tool_sequence: List[str],
    ) -> None:
        """
        仅记录运行时真实工具序列（不计入模板使用次数），用于在线学习转移概率。
        """
        payload = self._read_payload()
        payload.setdefault("user_tool_sequences", {})
        payload.setdefault("global_tool_transitions", {})
        payload.setdefault("user_tool_transitions", {})
        normalized_seq = [str(x).strip() for x in tool_sequence if str(x).strip()]
        if not normalized_seq:
            return
        user_seqs = payload["user_tool_sequences"].setdefault(user_id, [])
        user_seqs.append({"workflow_id": workflow_id, "tools": normalized_seq})
        if len(user_seqs) > 200:
            payload["user_tool_sequences"][user_id] = user_seqs[-200:]
        self._accumulate_transitions(payload, user_id=user_id, tools=normalized_seq)
        self._settings.set_setting(USAGE_STORE_KEY, payload)

    def recommend(
        self,
        *,
        workflow_id: str,
        user_id: str,
        current_tools: List[str],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        payload = self._read_payload()
        global_uses = payload.get("global_template_uses", {}) if isinstance(payload, dict) else {}
        user_uses = (
            payload.get("user_template_uses", {}).get(user_id, {})
            if isinstance(payload, dict)
            else {}
        )
        global_transitions = (
            payload.get("global_tool_transitions", {}) if isinstance(payload, dict) else {}
        )
        user_transitions = (
            payload.get("user_tool_transitions", {}).get(user_id, {})
            if isinstance(payload, dict)
            else {}
        )
        current_tool_set = {str(x).strip() for x in current_tools if str(x).strip()}
        current_tool_list = [x for x in current_tools if str(x).strip()]

        ranked: List[Dict[str, Any]] = []
        for tpl in TEMPLATES:
            overlap = len(current_tool_set.intersection(set(tpl.tools)))
            overlap_score = overlap * 3
            user_score = int(user_uses.get(tpl.template_id, 0)) * 2
            global_score = int(global_uses.get(tpl.template_id, 0))
            transition_score, transition_confidence, transition_pairs = self._score_transition_signal(
                current_tools=current_tool_list,
                template_tools=tpl.tools,
                user_transitions=user_transitions,
                global_transitions=global_transitions,
            )
            cold_start_prior = 1 + min(3, int(global_uses.get(tpl.template_id, 0)))
            ranked.append(
                {
                    "id": tpl.template_id,
                    "name": tpl.name,
                    "description": tpl.description,
                    "tools": tpl.tools,
                    "score": overlap_score + user_score + global_score + transition_score + cold_start_prior,
                    "signals": {
                        "overlap": overlap,
                        "user_uses": int(user_uses.get(tpl.template_id, 0)),
                        "global_uses": int(global_uses.get(tpl.template_id, 0)),
                        "transition_score": transition_score,
                        "transition_confidence": transition_confidence,
                        "transition_pairs": transition_pairs,
                        "cold_start_prior": cold_start_prior,
                        "workflow_id": workflow_id,
                    },
                }
            )
        ranked.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
        return ranked[: max(1, int(limit or 5))]

    def _accumulate_transitions(
        self, payload: Dict[str, Any], *, user_id: str, tools: List[str]
    ) -> None:
        if len(tools) < 2:
            return
        global_transitions = payload.setdefault("global_tool_transitions", {})
        user_all = payload.setdefault("user_tool_transitions", {})
        user_transitions = user_all.setdefault(user_id, {})
        for i in range(len(tools) - 1):
            src = tools[i]
            dst = tools[i + 1]
            src_global = global_transitions.setdefault(src, {})
            src_global[dst] = int(src_global.get(dst, 0)) + 1
            src_user = user_transitions.setdefault(src, {})
            src_user[dst] = int(src_user.get(dst, 0)) + 1

    def _score_transition_signal(
        self,
        *,
        current_tools: List[str],
        template_tools: List[str],
        user_transitions: Dict[str, Any],
        global_transitions: Dict[str, Any],
    ) -> tuple[int, float, List[Dict[str, Any]]]:
        if not current_tools:
            return (0, 0.0, [])
        template_set = set(template_tools)
        raw_score = 0.0
        confidence = 0.0
        pairs: List[Dict[str, Any]] = []
        for src in current_tools:
            user_next = user_transitions.get(src, {}) if isinstance(user_transitions, dict) else {}
            global_next = global_transitions.get(src, {}) if isinstance(global_transitions, dict) else {}
            for dst in template_set:
                u = float(user_next.get(dst, 0) or 0)
                g = float(global_next.get(dst, 0) or 0)
                # 用户行为权重大于全局行为
                w = u * 0.7 + g * 0.3
                raw_score += w
                confidence += u + g
                if w > 0:
                    pairs.append(
                        {
                            "from": src,
                            "to": dst,
                            "weight": round(w, 3),
                            "user_count": int(u),
                            "global_count": int(g),
                        }
                    )
        # 压缩到可解释区间，避免覆盖主信号
        bounded = int(min(8, round(raw_score)))
        conf = min(1.0, confidence / 20.0) if confidence > 0 else 0.0
        pairs.sort(key=lambda x: float(x.get("weight", 0.0)), reverse=True)
        return (bounded, conf, pairs[:3])

    def _read_payload(self) -> Dict[str, Any]:
        raw = self._settings.get_setting(USAGE_STORE_KEY, {})
        if isinstance(raw, dict):
            return raw
        return {}

