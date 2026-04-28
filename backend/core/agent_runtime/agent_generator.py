"""
自然语言 → Agent 创建草稿（经 InferenceGateway，不落库）。

设计约束（AGENTS.md）：
- 所有模型调用经 InferenceClient → Gateway
- 仅返回草稿，由用户确认后走现有 POST /api/agents 创建
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from log import logger
from pydantic import BaseModel, Field

from core.inference.client.inference_client import InferenceClient
from core.models.registry import get_model_registry
from core.security.skill_policy import filter_blocked_skills
from core.skills.discovery import SkillDiscoveryEngine, SkillSearchHit, get_discovery_engine


DRAFT_AGENT_SCOPE_ID = "__nl_agent_draft__"


class MatchedSkillBrief(BaseModel):
    skill_id: str
    name: str
    semantic_score: float = 0.0
    hybrid_score: float = 0.0


class AgentNlDraft(BaseModel):
    """与 CreateAgentRequest 对齐的草稿字段（无 agent_id）。"""

    name: str
    description: str = ""
    model_id: str
    system_prompt: str = ""
    enabled_skills: List[str] = Field(default_factory=list)
    execution_mode: str = "legacy"
    max_steps: int = 20
    temperature: float = 0.7


class GenerateAgentFromNlResult(BaseModel):
    draft: AgentNlDraft
    matched_skills: List[MatchedSkillBrief]
    llm_used: bool
    warnings: List[str] = Field(default_factory=list)


def _resolve_model_id(explicit: Optional[str]) -> str:
    reg = get_model_registry()
    if explicit:
        mid = explicit.strip()
        if reg.get_model(mid):
            return mid
        available = reg.list_models()
        if any(m.id == mid for m in available):
            return mid
        raise ValueError(f"model_id not found: {mid}")
    models = reg.list_models()
    if not models:
        raise ValueError("no_models_available")
    return models[0].id


def _collect_discovery_hits(
    engine: SkillDiscoveryEngine,
    description: str,
    top_k: int,
) -> List[SkillSearchHit]:
    return engine.search_hits(
        query=description.strip(),
        agent_id=DRAFT_AGENT_SCOPE_ID,
        organization_id=None,
        top_k=top_k,
        filters={"enabled_only": True},
        min_semantic_similarity=0.0,
        min_hybrid_score=0.0,
    )


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    s = (text or "").strip()
    if not s:
        return None
    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = s[start : end + 1]
    try:
        out = json.loads(blob)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _sanitize_execution_mode(raw: Any) -> str:
    if raw is None:
        return "legacy"
    v = str(raw).strip().lower()
    if v in {"plan_based", "plan-based"}:
        return "plan_based"
    return "legacy"


def _clamp_skills(suggested: Any, allowed: List[str]) -> List[str]:
    allow = set(allowed)
    out: List[str] = []
    seen: set[str] = set()
    if not isinstance(suggested, list):
        return []
    for item in suggested:
        sid = str(item).strip()
        if sid in allow and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def _fallback_draft(
    description: str,
    model_id: str,
    skill_ids: List[str],
) -> AgentNlDraft:
    title = description.strip().split("\n")[0].strip()
    if len(title) > 80:
        title = title[:77] + "..."
    name = title or "Custom Agent"
    safe_name = re.sub(r"[^\w\s\u4e00-\u9fff\-]", "", name)[:60].strip() or "Custom Agent"
    return AgentNlDraft(
        name=safe_name,
        description=description.strip()[:500],
        model_id=model_id,
        system_prompt=(
            "You are a capable assistant aligned with the user's goals.\n\n"
            "User intent:\n"
            f"{description.strip()[:4000]}"
        ),
        enabled_skills=skill_ids,
        execution_mode="legacy",
        max_steps=20,
        temperature=0.7,
    )


async def generate_agent_draft_from_nl(
    description: str,
    *,
    model_id: Optional[str] = None,
    top_skills: int = 12,
) -> GenerateAgentFromNlResult:
    """
    语义发现 Skill → LLM 生成名称/描述/system_prompt → 校验 skill 子集。
    """
    warnings: List[str] = []
    desc = (description or "").strip()
    if len(desc) < 4:
        raise ValueError("description_too_short")

    resolved_model = _resolve_model_id(model_id)
    engine = get_discovery_engine()
    hits = _collect_discovery_hits(engine, desc, top_k=max(1, min(top_skills, 32)))

    candidate_ids_full = [h.skill.id for h in hits]
    candidate_ids = filter_blocked_skills(candidate_ids_full)

    if len(candidate_ids) < len(candidate_ids_full):
        warnings.append("some_skills_filtered_by_security_policy")

    allowed_set = set(candidate_ids)
    matched_brief: List[MatchedSkillBrief] = []
    for h in hits:
        if h.skill.id not in allowed_set:
            continue
        matched_brief.append(
            MatchedSkillBrief(
                skill_id=h.skill.id,
                name=h.skill.name,
                semantic_score=h.semantic_score,
                hybrid_score=h.hybrid_score,
            )
        )
        if len(matched_brief) >= top_skills:
            break

    skill_catalog = []
    for h in hits[:20]:
        if h.skill.id not in candidate_ids:
            continue
        skill_catalog.append(
            f"- id={h.skill.id} name={h.skill.name!r} description={h.skill.description[:200]!r}"
        )
    catalog_text = "\n".join(skill_catalog) if skill_catalog else "(no matched skills)"

    llm_prompt = (
        "The user describes what they want an AI agent to do (local-first platform).\n"
        "Return ONLY a JSON object with keys:\n"
        '  "name": short display name (max 60 chars),\n'
        '  "description": one sentence summary,\n'
        '  "system_prompt": detailed instructions for the agent (markdown ok),\n'
        '  "enabled_skills": array of skill id strings chosen ONLY from the candidate list below '
        "(subset allowed; empty array if none fit),\n"
        '  "execution_mode": "legacy" or "plan_based" (use plan_based only if multi-step tool use is likely).\n'
        "Rules: do not invent skill ids; prefer fewer skills; stay faithful to the user request.\n\n"
        f"User request:\n{desc}\n\n"
        f"Candidate skill ids (choose subset only):\n{json.dumps(candidate_ids, ensure_ascii=False)}\n\n"
        f"Skill details:\n{catalog_text}\n"
    )

    client = InferenceClient()
    llm_used = True
    try:
        resp = await client.generate(
            model=resolved_model,
            prompt=llm_prompt,
            system_prompt=(
                "You output only valid JSON objects. No markdown fences, no commentary."
            ),
            temperature=0.35,
            max_tokens=2048,
            metadata={
                "source": "agent_generator_nl",
                "operation": "draft_agent",
            },
        )
        raw_text = (resp.text or "").strip()
        parsed = _extract_json_object(raw_text)
        if not parsed:
            warnings.append("llm_json_parse_failed")
            llm_used = False
            draft = _fallback_draft(desc, resolved_model, candidate_ids[:8])
            return GenerateAgentFromNlResult(
                draft=draft,
                matched_skills=matched_brief,
                llm_used=False,
                warnings=warnings,
            )

        name = str(parsed.get("name") or "").strip() or "Custom Agent"
        name = name[:100]
        brief = str(parsed.get("description") or "").strip()[:500]
        sys_p = str(parsed.get("system_prompt") or "").strip()
        if len(sys_p) > 12000:
            sys_p = sys_p[:12000]
            warnings.append("system_prompt_truncated")

        picked = _clamp_skills(parsed.get("enabled_skills"), candidate_ids)
        if not picked and candidate_ids:
            picked = candidate_ids[: min(8, len(candidate_ids))]
            warnings.append("enabled_skills_fallback_to_discovery")

        exec_mode = _sanitize_execution_mode(parsed.get("execution_mode"))

        draft = AgentNlDraft(
            name=name,
            description=brief,
            model_id=resolved_model,
            system_prompt=sys_p,
            enabled_skills=picked,
            execution_mode=exec_mode,
            max_steps=20,
            temperature=0.7,
        )
        return GenerateAgentFromNlResult(
            draft=draft,
            matched_skills=matched_brief,
            llm_used=llm_used,
            warnings=warnings,
        )
    except Exception as e:
        logger.warning("[AgentGenerator] LLM draft failed: %s", e)
        warnings.append("llm_call_failed")
        draft = _fallback_draft(desc, resolved_model, candidate_ids[:8])
        return GenerateAgentFromNlResult(
            draft=draft,
            matched_skills=matched_brief,
            llm_used=False,
            warnings=warnings,
        )
