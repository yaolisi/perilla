from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Tuple

GUARD_SECTIONS: Tuple[str, ...] = ("preflight", "mapping", "payload", "validator", "workflow")


def parse_guard_log_text(text: str, sections: Tuple[str, ...] = GUARD_SECTIONS) -> Dict[str, str]:
    status = dict.fromkeys(sections, "missing")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        for section in sections:
            if line == f"[guard] {section}":
                status[section] = "seen"
    return status


def summarize_guard_log(path: str, sections: Tuple[str, ...] = GUARD_SECTIONS) -> tuple[Dict[str, str], List[str]]:
    p = Path(path)
    if not p.exists():
        return dict.fromkeys(sections, "missing"), []
    text = p.read_text(encoding="utf-8", errors="ignore")
    status = parse_guard_log_text(text, sections=sections)
    seen = sections_seen_from_status(status, sections=sections)
    return status, seen


def sections_seen_from_status(status: Mapping[str, str], sections: Tuple[str, ...] = GUARD_SECTIONS) -> List[str]:
    return [section for section in sections if status.get(section) == "seen"]
