from __future__ import annotations

import json
from pathlib import Path


def test_frontend_package_json_includes_vitest_unit_scripts() -> None:
    root = Path(__file__).resolve().parents[2]
    pkg_path = root / "frontend" / "package.json"
    payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})

    assert scripts.get("test:unit") == "vitest run"
    assert scripts.get("test:unit:coverage") == "vitest run --coverage"
