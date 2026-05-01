"""Helm Deployment 模板中容器 env 列表不得出现重复 - name:（大写变量名），以免渲染或运行时歧义。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_ENV_LINE = re.compile(r"^\s+- name: ([A-Z]\w*)\s*$")
_KEY_LINE = re.compile(r"^[a-zA-Z_]\w*:")


def _find_env_block(lines: list[str]) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        if re.match(r"^\s+env:\s*$", line):
            base = len(line) - len(line.lstrip())
            return i, base
    return None


def _env_block_ended(stripped: str, ind: int, base_indent: int) -> bool:
    if ind != base_indent:
        return False
    if stripped.startswith("{{-") or stripped.startswith("#"):
        return False
    return bool(_KEY_LINE.match(stripped))


def _duplicate_uppercase_env_names(raw: str) -> tuple[list[str], str | None]:
    lines = raw.splitlines()
    found = _find_env_block(lines)
    if found is None:
        return [], "missing container env: block"
    env_idx, base_indent = found

    first_line: dict[str, int] = {}
    out: list[str] = []

    for j in range(env_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped:
            continue
        ind = len(line) - len(line.lstrip())
        if _env_block_ended(stripped, ind, base_indent):
            break

        m = _ENV_LINE.match(line)
        if not m:
            continue
        name = m.group(1)
        ln = j + 1
        if name in first_line:
            out.append(f"{name!r} (lines {first_line[name]} and {ln})")
        else:
            first_line[name] = ln

    return out, None


def test_helm_deployment_template_has_no_duplicate_env_var_names() -> None:
    p = repo_path("deploy/helm/perilla-backend/templates/deployment.yaml")
    assert p.is_file()
    raw = p.read_text(encoding="utf-8")
    dups, err = _duplicate_uppercase_env_names(raw)
    assert err is None, err
    assert not dups, "duplicate env - name entries in deployment.yaml: " + "; ".join(dups)
