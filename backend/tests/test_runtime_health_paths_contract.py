"""本地 healthcheck 与 Compose 容器 healthcheck 须命中网关标准存活路径（与 K8s 探针一致）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo


def test_healthcheck_script_uses_standard_backend_ports_and_paths() -> None:
    raw = repo_path("scripts/healthcheck.sh").read_text(encoding="utf-8")
    assert 'BACKEND_PORT="${BACKEND_PORT:-8000}"' in raw
    assert 'curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health"' in raw
    assert "api/health/ready" in raw


def test_docker_compose_backend_healthcheck_hits_api_health() -> None:
    raw = repo_path("docker-compose.yml").read_text(encoding="utf-8")
    assert "http://localhost:8000/api/health" in raw
    assert 'PORT: "8000"' in raw
