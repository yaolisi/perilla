"""Helm Pod/容器 securityContext 须与 docker/backend.Dockerfile 的 UID/GID 一致（避免镜像跑不起来）。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo


def _is_top_level_line(line: str) -> bool:
    return not line[:1].isspace()


def _try_capture_direct_child(out: dict[str, str], line: str) -> None:
    m = re.match(r"^ {2}([^:]+):\s*(.*)$", line)
    if not m:
        return
    key = m.group(1).strip()
    val = m.group(2).strip().strip('"').strip("'")
    out[key] = val


def _direct_scalars_under_top_level_block(raw: str, block: str) -> dict[str, str]:
    """解析顶层块下第一层 `  key: value` 标量（忽略更深嵌套如 capabilities.drop）。"""
    lines = raw.splitlines()
    inside = False
    out: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _is_top_level_line(line):
            if stripped.startswith(f"{block}:"):
                inside = True
                continue
            if inside:
                break
            continue
        if inside:
            _try_capture_direct_child(out, line)
    return out


def test_helm_pod_and_container_run_as_uid_match_dockerfile() -> None:
    raw = repo_path("deploy/helm/perilla-backend/values.yaml").read_text(encoding="utf-8")
    pod = _direct_scalars_under_top_level_block(raw, "podSecurityContext")
    cnt = _direct_scalars_under_top_level_block(raw, "securityContext")

    assert pod.get("runAsNonRoot") == "true"
    assert pod.get("runAsUser") == "1000"
    assert pod.get("runAsGroup") == "1000"

    assert cnt.get("runAsNonRoot") == "true"
    assert cnt.get("runAsUser") == "1000"

    dkf = repo_path("docker/backend.Dockerfile").read_text(encoding="utf-8")
    assert "groupadd --gid 1000" in dkf
    assert "--uid 1000" in dkf
