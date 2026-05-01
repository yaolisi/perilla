"""Helm 默认 Service 端口须与 containerPort / env.port 一致，避免摘流或 Ingress 指错后端端口。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo


def _top_level_int(raw: str, key: str) -> int | None:
    m = re.search(rf"(?m)^{re.escape(key)}:\s*(\d+)\s*$", raw)
    return int(m.group(1)) if m else None


def _service_port(raw: str) -> int | None:
    lines = raw.splitlines()
    in_service = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        is_top = not line[:1].isspace()
        if is_top and stripped.startswith("service:"):
            in_service = True
            continue
        if is_top and in_service:
            break
        if in_service:
            mp = re.match(r"^\s+port:\s*(\d+)\s*$", line)
            if mp:
                return int(mp.group(1))
    return None


def _env_listen_port(raw: str) -> str | None:
    lines = raw.splitlines()
    in_env = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        is_top = not line[:1].isspace()
        if is_top and stripped.startswith("env:"):
            in_env = True
            continue
        if is_top and in_env:
            break
        if in_env:
            mp = re.match(r'^\s+port:\s*"(\d+)"\s*$', line)
            if mp:
                return mp.group(1)
    return None


def test_helm_values_service_port_matches_container_port_and_env_port() -> None:
    raw = repo_path("deploy/helm/perilla-backend/values.yaml").read_text(encoding="utf-8")
    cp = _top_level_int(raw, "containerPort")
    sp = _service_port(raw)
    ep = _env_listen_port(raw)

    assert cp == 8000, "values.yaml containerPort default must be 8000 for chart parity"
    assert sp == 8000, "values.yaml service.port must match containerPort"
    assert cp == sp
    assert ep == str(cp), "values.yaml env.port must match containerPort as quoted string"
