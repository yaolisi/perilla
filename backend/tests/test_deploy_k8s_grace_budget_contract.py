"""deploy 示例与 Helm 默认值：Pod 宽限期须为 preStop + Uvicorn 关停留出预算（合约）。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path


# 示例注释中推荐的 uvicorn 关停秒数（40）+ 少量连接释放余量
_MIN_SECONDS_AFTER_PRESTOP_FOR_APP_SHUTDOWN = 45


def _first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, flags=re.MULTILINE)
    return int(m.group(1)) if m else None


@pytest.mark.requires_monorepo
def test_backend_deployment_example_termination_budget() -> None:
    p = repo_path("deploy/k8s/backend-deployment.example.yaml")
    assert p.is_file(), "expected monorepo deploy example"
    raw = p.read_text(encoding="utf-8")
    tgp = _first_int(r"^\s*terminationGracePeriodSeconds:\s*(\d+)\s*$", raw)
    prestop = _first_int(r"sleep\s+(\d+)", raw)
    assert tgp is not None and prestop is not None
    assert tgp >= prestop + _MIN_SECONDS_AFTER_PRESTOP_FOR_APP_SHUTDOWN, (
        f"terminationGracePeriodSeconds ({tgp}) should leave >= "
        f"{_MIN_SECONDS_AFTER_PRESTOP_FOR_APP_SHUTDOWN}s after preStop ({prestop}s) for uvicorn + lifespan cleanup"
    )


@pytest.mark.requires_monorepo
def test_helm_values_default_termination_budget() -> None:
    p = repo_path("deploy/helm/perilla-backend/values.yaml")
    assert p.is_file()
    raw = p.read_text(encoding="utf-8")
    tgp = _first_int(r"^terminationGracePeriodSeconds:\s*(\d+)\s*$", raw)
    prestop = _first_int(r"^\s*preStopSleepSeconds:\s*(\d+)\s*$", raw)
    assert tgp is not None and prestop is not None
    assert tgp >= prestop + _MIN_SECONDS_AFTER_PRESTOP_FOR_APP_SHUTDOWN
