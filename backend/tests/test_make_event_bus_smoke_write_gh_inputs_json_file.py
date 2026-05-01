from __future__ import annotations

import pytest

from tests.repo_paths import repo_root

pytestmark = pytest.mark.requires_monorepo

import hashlib
import json
import subprocess
from pathlib import Path


def test_make_write_gh_inputs_json_file_writes_valid_snapshot(tmp_path: Path) -> None:
    output_file = tmp_path / "gh-inputs.json"
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-write-gh-inputs-json-file",
            f"EVENT_BUS_SMOKE_GH_INPUTS_JSON_FILE={output_file}",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
    )
    assert result.returncode == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert isinstance(payload["generated_at_ms"], int)
    assert payload["generated_at_ms"] > 0
    assert payload["source"] == "make event-bus-smoke-write-gh-inputs-json-file"
    assert payload["workflow"]
    assert payload["summary_schema_mode"] in {"strict", "compatible"}
    assert payload["payload_sha256_mode"] in {"strict", "off"}
    assert isinstance(payload.get("payload_sha256"), str) and payload["payload_sha256"]
    core = dict(payload)
    digest = core.pop("payload_sha256")
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
