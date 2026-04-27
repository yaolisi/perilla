from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from scripts.validate_event_bus_smoke_gh_inputs_snapshot import validate_payload as validate_gh_snapshot_payload
from scripts.validate_event_bus_smoke_gh_trigger_inputs_audit import validate_payload as validate_gh_trigger_payload
from scripts.validate_event_bus_smoke_summary_result import validate_payload as validate_summary_payload


def _with_payload_hash(payload: Dict[str, Any], key: str = "payload_sha256") -> Dict[str, Any]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core[key] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def test_summary_validator_errors_are_code_prefixed() -> None:
    errors = validate_summary_payload({}, expected_summary_schema_version=0)
    assert errors
    assert all(error.startswith("[") for error in errors)


def test_gh_trigger_validator_errors_are_code_prefixed() -> None:
    errors = validate_gh_trigger_payload({}, payload_sha256_mode="bad")
    assert errors
    assert all(error.startswith("[") for error in errors)


def test_gh_snapshot_validator_errors_are_code_prefixed() -> None:
    payload = {
        "schema_version": 1,
        "generated_at_ms": 1710000000000,
        "source": "make event-bus-smoke-write-gh-inputs-json-file",
        "workflow": "event-bus-dlq-smoke.yml",
        "base_url": "http://127.0.0.1:8000",
        "event_type": "agent.status.changed",
        "limit": "20",
        "expected_schema_version": "1",
        "expected_summary_schema_version": "1",
        "summary_schema_mode": "strict",
        "payload_sha256_mode": "strict",
        "result_file_stale_threshold_ms": "600000",
        "file_suffix": "",
    }
    payload = _with_payload_hash(payload)
    payload["workflow"] = ""
    errors = validate_gh_snapshot_payload(payload)
    assert errors
    assert all(error.startswith("[") for error in errors)
