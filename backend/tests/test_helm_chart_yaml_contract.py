"""Helm Chart.yaml 元数据须完整且版本可解析（避免 chart 发布/依赖引用失败）。"""

from __future__ import annotations

import re

import pytest

from tests.repo_paths import repo_path

pytestmark = pytest.mark.requires_monorepo

_CHART_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_LINE = re.compile(r"^([a-zA-Z0-9]+):\s*(.*?)\s*$")


def _first_level_chart_fields(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if line.strip().startswith("#") or not line.strip():
            continue
        if not line[0].isspace():
            m = _LINE.match(line.rstrip())
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def test_helm_chart_yaml_metadata() -> None:
    p = repo_path("deploy/helm/perilla-backend/Chart.yaml")
    assert p.is_file()
    fields = _first_level_chart_fields(p.read_text(encoding="utf-8"))
    assert fields.get("apiVersion") == "v2"
    assert fields.get("name") == "perilla-backend"
    assert fields.get("type") == "application"
    ver = fields.get("version")
    assert ver, "Chart.version must be present"
    assert _CHART_SEMVER.match(ver), f"Chart.version must look like semver: {ver!r}"
    app_ver = fields.get("appVersion")
    assert app_ver, "Chart.appVersion must be non-empty"
