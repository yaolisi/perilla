"""Helm values.yaml 的 env: 平铺键不得重复（PyYAML 会静默覆盖，易导致生产误配）。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_TOP_LEVEL = re.compile(r"^[a-zA-Z_]\w*:\s*")
_ENV_KEY = re.compile(r"^ {2}(\w+):\s*")


def _duplicate_env_keys_in_values_yaml(raw: str) -> list[str]:
    lines = raw.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if re.match(r"^env:\s*(#.*)?$", line):
            start = i + 1
            break
    if start is None:
        return ["<missing top-level env:>"]

    out: list[str] = []
    first_line: dict[str, int] = {}
    for i in range(start, len(lines)):
        line = lines[i]
        if _TOP_LEVEL.match(line) and not line.startswith(" "):
            break
        m = _ENV_KEY.match(line)
        if not m:
            continue
        k = m.group(1)
        if k in first_line:
            out.append(f"{k!r} (first line {first_line[k]}, duplicate line {i + 1})")
        else:
            first_line[k] = i + 1
    return out


def test_helm_values_env_section_has_no_duplicate_keys() -> None:
    p = repo_path("deploy/helm/perilla-backend/values.yaml")
    assert p.is_file()
    dups = _duplicate_env_keys_in_values_yaml(p.read_text(encoding="utf-8"))
    assert not dups, "env: duplicate keys in values.yaml: " + "; ".join(dups)
