from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_make_contract_guard_status_json_for_missing_log() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-contract-guard-status-json",
            "EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE=.tmp/__missing_guard__.log",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["log_file"].endswith("__missing_guard__.log")
    assert payload["log_file_exists"] is False
    assert payload["sections_seen"] == []
    assert payload["status"]["preflight"] == "missing"


def test_make_contract_guard_status_json_for_existing_log(tmp_path: Path) -> None:
    guard_log = tmp_path / "guard.log"
    guard_log.write_text("[guard] preflight\n[guard] payload\n", encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-contract-guard-status-json",
            f"EVENT_BUS_SMOKE_CONTRACT_GUARD_LOG_FILE={guard_log}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["log_file_exists"] is True
    assert payload["sections_seen"] == ["preflight", "payload"]
    assert payload["status"]["preflight"] == "seen"
    assert payload["status"]["payload"] == "seen"
