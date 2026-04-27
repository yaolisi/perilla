from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from scripts.event_bus_smoke_error_codes import (
    ERR_GUARD_LOG_FILE_INVALID,
    ERR_GUARD_SECTIONS_SEEN_ITEM_INVALID,
    ERR_GUARD_SEEN_REQUIRES_EMPTY_WHEN_LOG_MISSING,
    ERR_GUARD_SECTIONS_SEEN_DUPLICATES,
    ERR_GUARD_SECTIONS_SEEN_UNSUPPORTED,
    ERR_GUARD_SEEN_STATUS_INCONSISTENT,
    ERR_GUARD_STATUS_REQUIRES_MISSING_WHEN_LOG_MISSING,
    ERR_GUARD_STATUS_INVALID_VALUE,
    ERR_GUARD_STATUS_KEY_MISMATCH,
    ERR_HEALTH_CONTRACT_MISMATCH_MUST_NOT_GREEN,
    ERR_HEALTH_PRECHECK_MISMATCH_REQUIRES_RED,
    ERR_HEALTH_REASON_CODES_MISMATCH,
    ERR_HEALTH_REASON_CODES_UNSUPPORTED,
    ERR_PAYLOAD_SHA256_MISMATCH,
    ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE,
    ERR_SUMMARY_SCHEMA_VERSION_INVALID,
    ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
    ERR_SUMMARY_SCHEMA_MODE_INVALID,
    ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID,
)
from scripts.event_bus_smoke_summary_keys import (
    KEY_CONTRACT_CHECK,
    KEY_CONTRACT_REASON_CODE,
    KEY_CONTRACT_REASON_KNOWN,
    KEY_HEALTH,
    KEY_HEALTH_REASON,
    KEY_HEALTH_REASON_CODES,
    KEY_LOG_FILE,
    KEY_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_PAYLOAD_SHA256,
    KEY_PREFLIGHT_CHECK,
    KEY_PREFLIGHT_REASON,
    KEY_PREFLIGHT_REASON_KNOWN,
    KEY_RESULT_FILE,
    KEY_RESULT_FILE_EXISTS,
    KEY_RESULT_GENERATED_AT_MS,
    KEY_RESULT_SCHEMA_VERSION,
    KEY_SUMMARY_SCHEMA_VERSION,
)
from scripts.validate_event_bus_smoke_summary_result import validate_payload


def _with_payload_hash(payload: Dict[str, Any]) -> Dict[str, Any]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core[KEY_PAYLOAD_SHA256] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def _base_payload() -> Dict[str, Any]:
    return _with_payload_hash(
        {
        KEY_SUMMARY_SCHEMA_VERSION: 1,
        KEY_HEALTH: "green",
        KEY_HEALTH_REASON: "all_checks_ok",
        KEY_HEALTH_REASON_CODES: ["all_checks_ok"],
        KEY_PREFLIGHT_CHECK: "ok",
        KEY_PREFLIGHT_REASON: "preflight_passed",
        KEY_PREFLIGHT_REASON_KNOWN: True,
        KEY_CONTRACT_CHECK: "ok",
        KEY_CONTRACT_REASON_CODE: "schema_match+generated_at_valid",
        KEY_CONTRACT_REASON_KNOWN: True,
        KEY_RESULT_SCHEMA_VERSION: 1,
        KEY_RESULT_GENERATED_AT_MS: 1710000000000,
        KEY_RESULT_FILE: "event-bus-smoke-result.json",
        KEY_RESULT_FILE_EXISTS: True,
        KEY_LOG_FILE: "event-bus-smoke.log",
        KEY_LOG_FILE_EXISTS: True,
        KEY_CONTRACT_GUARD_LOG_FILE: "event-bus-smoke-contract-guard.log",
        KEY_CONTRACT_GUARD_LOG_FILE_EXISTS: True,
        KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight", "mapping"],
        KEY_CONTRACT_GUARD_STATUS: {
            "preflight": "seen",
            "mapping": "seen",
            "payload": "missing",
            "validator": "missing",
            "workflow": "missing",
        },
        }
    )


def test_validate_payload_accepts_valid_summary_contract() -> None:
    assert validate_payload(_base_payload()) == []


def test_validate_payload_rejects_health_reason_code_mismatch() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH_REASON] = "contract:schema_version_mismatch"
    payload[KEY_HEALTH_REASON_CODES] = ["all_checks_ok"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("health_reason_codes must match parsed health_reason" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_preflight_mismatch_not_red() -> None:
    payload = _base_payload()
    payload[KEY_PREFLIGHT_CHECK] = "mismatch"
    payload[KEY_HEALTH] = "yellow"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("health must be red when preflight_contract_check == mismatch" in e for e in errors)
    assert any(f"[{ERR_HEALTH_PRECHECK_MISMATCH_REQUIRES_RED}]" in e for e in errors)


def test_validate_payload_rejects_registry_degraded_green() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH_REASON] = "registry:unknown_reason_code_detected"
    payload[KEY_HEALTH_REASON_CODES] = ["registry:unknown_reason_code_detected"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("health must not be green" in e for e in errors)
    assert any(f"[{ERR_HEALTH_CONTRACT_MISMATCH_MUST_NOT_GREEN}]" in e for e in errors)


def test_validate_payload_accepts_summary_payload_key_mismatch_reason_code() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH] = "red"
    payload[KEY_HEALTH_REASON] = "summary_payload_key_mismatch"
    payload[KEY_HEALTH_REASON_CODES] = ["summary_payload_key_mismatch"]
    payload[KEY_PREFLIGHT_CHECK] = "mismatch"
    payload[KEY_PREFLIGHT_REASON] = "missing_preflight_status"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    assert validate_payload(payload) == []


def test_validate_payload_rejects_unknown_health_reason_code() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH_REASON] = "unknown_code"
    payload[KEY_HEALTH_REASON_CODES] = ["unknown_code"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("health_reason_codes[] contains unsupported code" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_UNSUPPORTED}]" in e for e in errors)


def test_validate_payload_accepts_result_fields_null() -> None:
    payload = _base_payload()
    payload[KEY_RESULT_SCHEMA_VERSION] = None
    payload[KEY_RESULT_GENERATED_AT_MS] = None
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    assert validate_payload(payload) == []


def test_validate_payload_rejects_non_positive_result_generated_at() -> None:
    payload = _base_payload()
    payload[KEY_RESULT_GENERATED_AT_MS] = 0
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("result_generated_at_ms must be > 0 when present" in e for e in errors)
    assert any(f"[{ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE}]" in e for e in errors)


def test_validate_payload_rejects_invalid_guard_sections_seen() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = ["preflight", "unknown"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen contains unsupported section" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_UNSUPPORTED}]" in e for e in errors)
    assert any('details={"unsupported":["unknown"]}' in e for e in errors)


def test_validate_payload_rejects_non_string_guard_sections_seen_item() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = ["preflight", 1]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen[] must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_ITEM_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_invalid_guard_status_shape() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_STATUS] = {"preflight": "seen"}
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_status must contain all guard sections" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_KEY_MISMATCH}]" in e for e in errors)
    assert any('details={"extra_keys":' in e and '"missing_keys":' in e for e in errors)


def test_validate_payload_rejects_guard_seen_status_inconsistency() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = ["mapping", "preflight"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must match contract_guard_status order/content" in e for e in errors)
    assert any(f"[{ERR_GUARD_SEEN_STATUS_INCONSISTENT}]" in e for e in errors)
    assert any('details={"actual":' in e and '"expected":' in e for e in errors)


def test_validate_payload_rejects_guard_seen_duplicates() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = ["preflight", "preflight"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must not contain duplicates" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_DUPLICATES}]" in e for e in errors)
    assert any('details={"duplicates":["preflight"]}' in e for e in errors)


def test_validate_payload_rejects_invalid_guard_status_value() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_STATUS]["payload"] = "invalid"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_status[payload] must be seen|missing" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_INVALID_VALUE}]" in e for e in errors)
    assert any('details={"actual":"invalid","allowed":["seen","missing"]}' in e for e in errors)


def test_validate_payload_rejects_missing_guard_log_file_string() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_LOG_FILE] = ""
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_log_file must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_GUARD_LOG_FILE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_seen_sections_when_guard_log_missing() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_LOG_FILE_EXISTS] = False
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = ["preflight"]
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must be empty when contract_guard_log_file_exists is false" in e for e in errors)
    assert any(f"[{ERR_GUARD_SEEN_REQUIRES_EMPTY_WHEN_LOG_MISSING}]" in e for e in errors)


def test_validate_payload_rejects_non_missing_guard_status_when_guard_log_missing() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_LOG_FILE_EXISTS] = False
    payload[KEY_CONTRACT_GUARD_STATUS]["preflight"] = "seen"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload)
    assert any("contract_guard_status values must all be missing when contract_guard_log_file_exists is false" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_REQUIRES_MISSING_WHEN_LOG_MISSING}]" in e for e in errors)


def test_validate_payload_accepts_guard_fields_when_log_missing_and_all_missing_state() -> None:
    payload = _base_payload()
    payload[KEY_CONTRACT_GUARD_LOG_FILE_EXISTS] = False
    payload[KEY_CONTRACT_GUARD_SECTIONS_SEEN] = []
    payload[KEY_CONTRACT_GUARD_STATUS] = {
        "preflight": "missing",
        "mapping": "missing",
        "payload": "missing",
        "validator": "missing",
        "workflow": "missing",
    }
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    assert validate_payload(payload) == []


def test_validate_payload_rejects_non_positive_expected_schema_version_in_function() -> None:
    errors = validate_payload(_base_payload(), expected_summary_schema_version=0)
    assert any("expected_summary_schema_version must be a positive integer" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_accepts_older_schema_in_compatible_mode() -> None:
    payload = _base_payload()
    payload[KEY_SUMMARY_SCHEMA_VERSION] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    assert validate_payload(payload, expected_summary_schema_version=2, schema_mode="compatible") == []


def test_validate_payload_rejects_older_schema_in_strict_mode() -> None:
    payload = _base_payload()
    payload[KEY_SUMMARY_SCHEMA_VERSION] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != KEY_PAYLOAD_SHA256})
    errors = validate_payload(payload, expected_summary_schema_version=2, schema_mode="strict")
    assert any("summary_schema_version must be 2" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_invalid_schema_mode() -> None:
    errors = validate_payload(_base_payload(), schema_mode="invalid")
    assert any("schema_mode must be one of: strict,compatible" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_SCHEMA_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_payload_sha256_mismatch() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH] = "yellow"
    errors = validate_payload(payload)
    assert any("payload_sha256 mismatch" in e for e in errors)
    assert any(f"[{ERR_PAYLOAD_SHA256_MISMATCH}]" in e for e in errors)


def test_validate_payload_accepts_payload_sha256_mismatch_when_mode_off() -> None:
    payload = _base_payload()
    payload[KEY_HEALTH] = "yellow"
    assert validate_payload(payload, payload_sha256_mode="off") == []


def test_validate_payload_rejects_invalid_payload_sha256_mode() -> None:
    errors = validate_payload(_base_payload(), payload_sha256_mode="bad")
    assert any("payload_sha256_mode must be one of: strict,off" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID}]" in e for e in errors)


def test_validator_cli_returns_0_when_contract_valid(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary.json"
    valid.write_text(json.dumps(_base_payload(), ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(valid),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "summary contract validation passed" in result.stdout


def test_validator_cli_returns_1_when_contract_invalid(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-summary.json"
    payload = _base_payload()
    payload[KEY_HEALTH_REASON_CODES] = []
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(invalid),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "summary contract validation failed" in result.stdout


def test_validator_cli_returns_2_when_input_missing(tmp_path: Path) -> None:
    missing = tmp_path / "not-found-summary.json"
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(missing),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "summary file not found" in result.stdout


def test_validator_cli_accepts_compatible_schema_mode(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary-v1.json"
    payload = _base_payload()
    payload[KEY_SUMMARY_SCHEMA_VERSION] = 1
    valid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(valid),
            "--expected-summary-schema-version",
            "2",
            "--schema-mode",
            "compatible",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_validator_cli_accepts_payload_sha256_mode_off(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary-off.json"
    payload = _base_payload()
    payload[KEY_HEALTH] = "yellow"
    valid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(valid),
            "--payload-sha256-mode",
            "off",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
