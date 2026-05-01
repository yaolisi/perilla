from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo


def test_frontend_package_json_includes_vitest_unit_scripts() -> None:
    root = repo_root()
    pkg_path = root / "frontend" / "package.json"
    payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})

    assert scripts.get("test:unit") == "vitest run"
    assert scripts.get("test:unit:coverage") == "vitest run --coverage"
