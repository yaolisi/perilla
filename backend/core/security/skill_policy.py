"""
Security policy helpers for risky built-in skills.
"""
from __future__ import annotations

from typing import Iterable, List

from config.settings import settings


BLOCKED_DANGEROUS_SKILL_IDS = {
    "builtin_python.run",
    "builtin_shell.run",
    "builtin_file.write",
    "builtin_file.delete",
}


def filter_blocked_skills(skill_ids: Iterable[str]) -> List[str]:
    if bool(getattr(settings, "agent_allow_dangerous_skills", False)):
        return [str(s).strip() for s in skill_ids if str(s).strip()]
    return [
        str(s).strip()
        for s in skill_ids
        if str(s).strip() and str(s).strip() not in BLOCKED_DANGEROUS_SKILL_IDS
    ]


def get_blocked_skills(skill_ids: Iterable[str]) -> List[str]:
    if bool(getattr(settings, "agent_allow_dangerous_skills", False)):
        return []
    return sorted(
        {str(s).strip() for s in skill_ids if str(s).strip() in BLOCKED_DANGEROUS_SKILL_IDS}
    )
