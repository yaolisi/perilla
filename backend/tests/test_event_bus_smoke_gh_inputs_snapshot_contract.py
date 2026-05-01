from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

from scripts.event_bus_smoke_error_codes import (
    ERR_GH_SNAPSHOT_GENERATED_AT_POSITIVE_INVALID,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MISMATCH,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_INVALID,
    ERR_GH_SNAPSHOT_SUMMARY_SCHEMA_MODE_INVALID,
)
from scripts.event_bus_smoke_gh_contract_keys import GH_INPUTS_SNAPSHOT_EXPECTED_KEYS
from scripts.validate_event_bus_smoke_gh_inputs_snapshot import validate_payload

from tests.repo_paths import repo_run_python


def _with_payload_hash(payload: Dict[str, Any]) -> Dict[str, Any]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core["payload_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def _base_payload() -> Dict[str, Any]:
    return _with_payload_hash(
        {
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
    )


def test_validate_payload_accepts_valid_contract() -> None:
    assert validate_payload(_base_payload()) == []


def test_validate_payload_rejects_invalid_mode() -> None:
    payload = _base_payload()
    payload["summary_schema_mode"] = "bad"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("summary_schema_mode must be strict|compatible" in e for e in errors)
    assert any(f"[{ERR_GH_SNAPSHOT_SUMMARY_SCHEMA_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_non_positive_generated_at_ms() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = 0
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("generated_at_ms must be > 0" in e for e in errors)
    assert any(f"[{ERR_GH_SNAPSHOT_GENERATED_AT_POSITIVE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_numeric_fields() -> None:
    payload = _base_payload()
    payload["schema_version"] = True
    payload["generated_at_ms"] = False
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("schema_version must be 1" in e for e in errors)
    assert any("generated_at_ms must be int" in e for e in errors)


def test_validate_payload_rejects_sha256_mismatch() -> None:
    payload = _base_payload()
    payload["workflow"] = "changed.yml"
    errors = validate_payload(payload)
    assert any("payload_sha256 mismatch" in e for e in errors)
    assert any(f"[{ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MISMATCH}]" in e for e in errors)


def test_validate_payload_accepts_sha256_mismatch_when_mode_off() -> None:
    payload = _base_payload()
    payload["workflow"] = "changed.yml"
    assert validate_payload(payload, payload_sha256_mode="off") == []


def test_validate_payload_rejects_invalid_sha256_mode() -> None:
    errors = validate_payload(_base_payload(), payload_sha256_mode="bad")
    assert any("payload_sha256_mode must be one of: strict,off" in e for e in errors)
    assert any(f"[{ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_expected_schema_version_in_function() -> None:
    errors = validate_payload(_base_payload(), expected_schema_version=True)  # type: ignore[arg-type]
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_rejects_non_positive_expected_schema_version_in_function() -> None:
    errors = validate_payload(_base_payload(), expected_schema_version=0)
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_rejects_missing_declared_key() -> None:
    payload = _base_payload()
    payload.pop("result_file_stale_threshold_ms", None)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("missing keys: result_file_stale_threshold_ms" in e for e in errors)


def test_validate_payload_rejects_extra_undeclared_key() -> None:
    payload = _base_payload()
    payload["unexpected"] = "1"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("unexpected" in e for e in errors)


def test_snapshot_expected_keys_match_base_payload() -> None:
    payload = _base_payload()
    assert set(payload.keys()) == set(GH_INPUTS_SNAPSHOT_EXPECTED_KEYS)


def test_validator_cli_returns_0_for_valid_payload(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_base_payload(), ensure_ascii=False), encoding="utf-8")
    result = repo_run_python(
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
        ["--input", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "validation passed" in result.stdout


def test_validator_cli_returns_1_for_invalid_payload(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    payload = _base_payload()
    payload["workflow"] = ""
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = repo_run_python(
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
        ["--input", str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "workflow must be non-empty string" in result.stdout


def test_validator_cli_accepts_sha256_mode_off(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    payload = _base_payload()
    payload["workflow"] = "changed.yml"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = repo_run_python(
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
        ["--input", str(path), "--payload-sha256-mode", "off"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
