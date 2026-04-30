from __future__ import annotations

import re
from pathlib import Path
from collections import Counter

from api.error_i18n import _ERROR_MESSAGES
import api.error_i18n as error_i18n


def test_error_i18n_covers_core_api_error_codes() -> None:
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "api" / "asr.py",
        root / "api" / "agents.py",
        root / "api" / "collaboration.py",
        root / "api" / "events.py",
        root / "api" / "memory.py",
        root / "api" / "vlm.py",
        root / "api" / "tools.py",
        root / "api" / "rag_trace.py",
        root / "api" / "skills.py",
        root / "api" / "mcp.py",
        root / "api" / "knowledge.py",
        root / "api" / "workflows.py",
        root / "api" / "chat.py",
    ]
    code_re = re.compile(r'code\\s*=\\s*"([a-z0-9_]+)"')

    found_codes: set[str] = set()
    for path in targets:
        found_codes.update(code_re.findall(path.read_text(encoding="utf-8")))

    missing = sorted(code for code in found_codes if code not in _ERROR_MESSAGES)
    assert missing == []


def test_grouped_error_maps_do_not_have_duplicate_keys() -> None:
    group_maps = []
    for name, value in vars(error_i18n).items():
        if not name.endswith("_ERROR_MESSAGES"):
            continue
        if name in {"_ERROR_MESSAGES", "MISC_ERROR_MESSAGES"}:
            continue
        if isinstance(value, dict):
            group_maps.append(value)

    counter: Counter[str] = Counter()
    for group in group_maps:
        counter.update(group.keys())

    duplicates = sorted([key for key, count in counter.items() if count > 1])
    assert duplicates == []

