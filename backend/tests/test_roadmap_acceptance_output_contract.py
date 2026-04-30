from __future__ import annotations

import json
import subprocess
import sys


from pathlib import Path


def test_roadmap_acceptance_output_json_contract(tmp_path) -> None:  # noqa: ANN001
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "roadmap-acceptance-output-contract.json"

    cmd = [
        sys.executable,
        "backend/scripts/roadmap_acceptance_smoke.py",
        "--base-url",
        "http://127.0.0.1:1",
        "--output-json",
        str(output),
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 1
    assert output.exists()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload.get("ok") is False
    assert payload.get("schema_version") == 1
    assert isinstance(payload.get("generated_at_ms"), int)
    assert isinstance(payload.get("release_gate"), dict)
    assert isinstance(payload.get("error"), str)
