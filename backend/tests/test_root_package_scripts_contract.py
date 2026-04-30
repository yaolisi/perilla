from __future__ import annotations

import json
from pathlib import Path


def test_root_package_json_includes_roadmap_acceptance_scripts() -> None:
    root = Path(__file__).resolve().parents[2]
    pkg_path = root / "package.json"
    payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})

    assert scripts.get("roadmap-acceptance-unit") == "make roadmap-acceptance-unit"
    assert scripts.get("roadmap-acceptance-smoke") == "make roadmap-acceptance-smoke"
    assert scripts.get("roadmap-acceptance-all") == "make roadmap-acceptance-all"
