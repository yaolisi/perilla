from __future__ import annotations

from typing import Any, Callable, Dict

from scripts.event_bus_smoke_error_codes import (
    ERR_GUARD_SECTIONS_SEEN_TYPE_INVALID,
    ERR_GUARD_STATUS_TYPE_INVALID,
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
    ERR_HEALTH_REASON_CODES_EMPTY,
    ERR_HEALTH_REASON_CODES_ITEM_INVALID,
    ERR_HEALTH_REASON_CODES_MISMATCH,
    ERR_HEALTH_REASON_CODES_UNSUPPORTED,
    ERR_PAYLOAD_SHA256_MISSING_OR_INVALID,
    ERR_PAYLOAD_SHA256_MISMATCH,
    ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE,
    ERR_RESULT_GENERATED_AT_MS_TYPE_INVALID,
    ERR_RESULT_SCHEMA_VERSION_NON_POSITIVE,
    ERR_RESULT_SCHEMA_VERSION_TYPE_INVALID,
    ERR_SUMMARY_SCHEMA_VERSION_INVALID,
    ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
    ERR_SUMMARY_SCHEMA_MODE_INVALID,
    ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID,
)
from scripts.event_bus_smoke_summary_keys import (
    KEY_HEALTH,
    KEY_HEALTH_REASON,
    KEY_HEALTH_REASON_CODES,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_PAYLOAD_SHA256,
    KEY_PREFLIGHT_CHECK,
    KEY_PREFLIGHT_REASON,
    KEY_RESULT_GENERATED_AT_MS,
    KEY_RESULT_SCHEMA_VERSION,
    KEY_SUMMARY_SCHEMA_VERSION,
)
from scripts.validate_event_bus_smoke_summary_result import validate_payload
from tests._event_bus_smoke_summary_fixtures import (
    base_summary_payload,
    rehash_payload,
)


def _payload_with(**updates: Any) -> Dict[str, Any]:
    payload = base_summary_payload()
    payload.update(updates)
    return rehash_payload(payload)


def _mutate_payload(mutator: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    payload = base_summary_payload()
    mutator(payload)
    return rehash_payload(payload)


def test_validate_payload_accepts_valid_summary_contract() -> None:
    assert validate_payload(base_summary_payload()) == []


def test_validate_payload_rejects_health_reason_code_mismatch() -> None:
    payload = _payload_with(
        **{
            KEY_HEALTH_REASON: "contract:schema_version_mismatch",
            KEY_HEALTH_REASON_CODES: ["all_checks_ok"],
        }
    )
    errors = validate_payload(payload)
    assert any("health_reason_codes must match parsed health_reason" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_preflight_mismatch_not_red() -> None:
    payload = _payload_with(**{KEY_PREFLIGHT_CHECK: "mismatch", KEY_HEALTH: "yellow"})
    errors = validate_payload(payload)
    assert any("health must be red when preflight_contract_check == mismatch" in e for e in errors)
    assert any(f"[{ERR_HEALTH_PRECHECK_MISMATCH_REQUIRES_RED}]" in e for e in errors)


def test_validate_payload_rejects_registry_degraded_green() -> None:
    payload = _payload_with(
        **{
            KEY_HEALTH_REASON: "registry:unknown_reason_code_detected",
            KEY_HEALTH_REASON_CODES: ["registry:unknown_reason_code_detected"],
        }
    )
    errors = validate_payload(payload)
    assert any("health must not be green" in e for e in errors)
    assert any(f"[{ERR_HEALTH_CONTRACT_MISMATCH_MUST_NOT_GREEN}]" in e for e in errors)


def test_validate_payload_accepts_summary_payload_key_mismatch_reason_code() -> None:
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "red"
    payload[KEY_HEALTH_REASON] = "summary_payload_key_mismatch"
    payload[KEY_HEALTH_REASON_CODES] = ["summary_payload_key_mismatch"]
    payload[KEY_PREFLIGHT_CHECK] = "mismatch"
    payload[KEY_PREFLIGHT_REASON] = "missing_preflight_status"
    payload = rehash_payload(payload)
    assert validate_payload(payload) == []


def test_validate_payload_rejects_unknown_health_reason_code() -> None:
    payload = _payload_with(
        **{KEY_HEALTH_REASON: "unknown_code", KEY_HEALTH_REASON_CODES: ["unknown_code"]}
    )
    errors = validate_payload(payload)
    assert any("health_reason_codes[] contains unsupported code" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_UNSUPPORTED}]" in e for e in errors)


def test_validate_payload_rejects_empty_health_reason_codes() -> None:
    payload = _payload_with(**{KEY_HEALTH_REASON_CODES: []})
    errors = validate_payload(payload)
    assert any("health_reason_codes must not be empty" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_EMPTY}]" in e for e in errors)


def test_validate_payload_rejects_non_string_health_reason_codes_item() -> None:
    payload = _payload_with(**{KEY_HEALTH_REASON_CODES: ["all_checks_ok", 1]})
    errors = validate_payload(payload)
    assert any("health_reason_codes[] must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_HEALTH_REASON_CODES_ITEM_INVALID}]" in e for e in errors)


def test_validate_payload_accepts_result_fields_null() -> None:
    payload = _payload_with(**{KEY_RESULT_SCHEMA_VERSION: None, KEY_RESULT_GENERATED_AT_MS: None})
    assert validate_payload(payload) == []


def test_validate_payload_rejects_non_positive_result_generated_at() -> None:
    payload = _payload_with(**{KEY_RESULT_GENERATED_AT_MS: 0})
    errors = validate_payload(payload)
    assert any("result_generated_at_ms must be > 0 when present" in e for e in errors)
    assert any(f"[{ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE}]" in e for e in errors)


def test_validate_payload_rejects_result_generated_at_type() -> None:
    payload = _payload_with(**{KEY_RESULT_GENERATED_AT_MS: "bad"})
    errors = validate_payload(payload)
    assert any("result_generated_at_ms must be int or null" in e for e in errors)
    assert any(f"[{ERR_RESULT_GENERATED_AT_MS_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_result_generated_at_type() -> None:
    payload = _payload_with(**{KEY_RESULT_GENERATED_AT_MS: True})
    errors = validate_payload(payload)
    assert any("result_generated_at_ms must be int or null" in e for e in errors)
    assert any(f"[{ERR_RESULT_GENERATED_AT_MS_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_result_schema_version_type() -> None:
    payload = _payload_with(**{KEY_RESULT_SCHEMA_VERSION: "bad"})
    errors = validate_payload(payload)
    assert any("result_schema_version must be int or null" in e for e in errors)
    assert any(f"[{ERR_RESULT_SCHEMA_VERSION_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_result_schema_version_type() -> None:
    payload = _payload_with(**{KEY_RESULT_SCHEMA_VERSION: True})
    errors = validate_payload(payload)
    assert any("result_schema_version must be int or null" in e for e in errors)
    assert any(f"[{ERR_RESULT_SCHEMA_VERSION_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_non_positive_result_schema_version() -> None:
    payload = _payload_with(**{KEY_RESULT_SCHEMA_VERSION: 0})
    errors = validate_payload(payload)
    assert any("result_schema_version must be > 0 when present" in e for e in errors)
    assert any(f"[{ERR_RESULT_SCHEMA_VERSION_NON_POSITIVE}]" in e for e in errors)


def test_validate_payload_rejects_invalid_guard_sections_seen() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight", "unknown"]})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen contains unsupported section" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_UNSUPPORTED}]" in e for e in errors)
    assert any('details={"unsupported":["unknown"]}' in e for e in errors)


def test_validate_payload_rejects_guard_sections_seen_type() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_SECTIONS_SEEN: "preflight"})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must be list" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_non_string_guard_sections_seen_item() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight", 1]})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen[] must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_ITEM_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_invalid_guard_status_shape() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_STATUS: {"preflight": "seen"}})
    errors = validate_payload(payload)
    assert any("contract_guard_status must contain all guard sections" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_KEY_MISMATCH}]" in e for e in errors)
    assert any('details={"extra_keys":' in e and '"missing_keys":' in e for e in errors)


def test_validate_payload_rejects_guard_status_type() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_STATUS: "seen"})
    errors = validate_payload(payload)
    assert any("contract_guard_status must be object" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_TYPE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_guard_seen_status_inconsistency() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["mapping", "preflight"]})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must match contract_guard_status order/content" in e for e in errors)
    assert any(f"[{ERR_GUARD_SEEN_STATUS_INCONSISTENT}]" in e for e in errors)
    assert any('details={"actual":' in e and '"expected":' in e for e in errors)


def test_validate_payload_rejects_guard_seen_duplicates() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight", "preflight"]})
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must not contain duplicates" in e for e in errors)
    assert any(f"[{ERR_GUARD_SECTIONS_SEEN_DUPLICATES}]" in e for e in errors)
    assert any('details={"duplicates":["preflight"]}' in e for e in errors)


def test_validate_payload_rejects_invalid_guard_status_value() -> None:
    def mutate(payload: Dict[str, Any]) -> None:
        payload[KEY_CONTRACT_GUARD_STATUS]["payload"] = "invalid"

    payload = _mutate_payload(mutate)
    errors = validate_payload(payload)
    assert any("contract_guard_status[payload] must be seen|missing" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_INVALID_VALUE}]" in e for e in errors)
    assert any('details={"actual":"invalid","allowed":["seen","missing"]}' in e for e in errors)


def test_validate_payload_rejects_missing_guard_log_file_string() -> None:
    payload = _payload_with(**{KEY_CONTRACT_GUARD_LOG_FILE: ""})
    errors = validate_payload(payload)
    assert any("contract_guard_log_file must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_GUARD_LOG_FILE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_seen_sections_when_guard_log_missing() -> None:
    payload = _payload_with(
        **{
            KEY_CONTRACT_GUARD_LOG_FILE_EXISTS: False,
            KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight"],
        }
    )
    errors = validate_payload(payload)
    assert any("contract_guard_sections_seen must be empty when contract_guard_log_file_exists is false" in e for e in errors)
    assert any(f"[{ERR_GUARD_SEEN_REQUIRES_EMPTY_WHEN_LOG_MISSING}]" in e for e in errors)


def test_validate_payload_rejects_non_missing_guard_status_when_guard_log_missing() -> None:
    def mutate(payload: Dict[str, Any]) -> None:
        payload[KEY_CONTRACT_GUARD_LOG_FILE_EXISTS] = False
        payload[KEY_CONTRACT_GUARD_STATUS]["preflight"] = "seen"

    payload = _mutate_payload(mutate)
    errors = validate_payload(payload)
    assert any("contract_guard_status values must all be missing when contract_guard_log_file_exists is false" in e for e in errors)
    assert any(f"[{ERR_GUARD_STATUS_REQUIRES_MISSING_WHEN_LOG_MISSING}]" in e for e in errors)


def test_validate_payload_accepts_guard_fields_when_log_missing_and_all_missing_state() -> None:
    payload = _payload_with(
        **{
            KEY_CONTRACT_GUARD_LOG_FILE_EXISTS: False,
            KEY_CONTRACT_GUARD_SECTIONS_SEEN: [],
            KEY_CONTRACT_GUARD_STATUS: {
                "preflight": "missing",
                "mapping": "missing",
                "payload": "missing",
                "validator": "missing",
                "workflow": "missing",
            },
        }
    )
    assert validate_payload(payload) == []


def test_validate_payload_rejects_non_positive_expected_schema_version_in_function() -> None:
    errors = validate_payload(base_summary_payload(), expected_summary_schema_version=0)
    assert any("expected_summary_schema_version must be a positive integer" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_expected_schema_version_in_function() -> None:
    errors = validate_payload(base_summary_payload(), expected_summary_schema_version=True)
    assert any("expected_summary_schema_version must be a positive integer" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_accepts_older_schema_in_compatible_mode() -> None:
    payload = _payload_with(**{KEY_SUMMARY_SCHEMA_VERSION: 1})
    assert validate_payload(payload, expected_summary_schema_version=2, schema_mode="compatible") == []


def test_validate_payload_rejects_older_schema_in_strict_mode() -> None:
    payload = _payload_with(**{KEY_SUMMARY_SCHEMA_VERSION: 1})
    errors = validate_payload(payload, expected_summary_schema_version=2, schema_mode="strict")
    assert any("summary_schema_version must be 2" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_summary_schema_version() -> None:
    payload = _payload_with(**{KEY_SUMMARY_SCHEMA_VERSION: True})
    errors = validate_payload(payload)
    assert any("summary_schema_version must be 1" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_SCHEMA_VERSION_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_invalid_schema_mode() -> None:
    errors = validate_payload(base_summary_payload(), schema_mode="invalid")
    assert any("schema_mode must be one of: strict,compatible" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_SCHEMA_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_payload_sha256_mismatch() -> None:
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "yellow"
    errors = validate_payload(payload)
    assert any("payload_sha256 mismatch" in e for e in errors)
    assert any(f"[{ERR_PAYLOAD_SHA256_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_missing_payload_sha256() -> None:
    payload = base_summary_payload()
    payload.pop(KEY_PAYLOAD_SHA256, None)
    errors = validate_payload(payload)
    assert any("payload_sha256 must be non-empty string" in e for e in errors)
    assert any(f"[{ERR_PAYLOAD_SHA256_MISSING_OR_INVALID}]" in e for e in errors)


def test_validate_payload_accepts_payload_sha256_mismatch_when_mode_off() -> None:
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "yellow"
    assert validate_payload(payload, payload_sha256_mode="off") == []


def test_validate_payload_rejects_invalid_payload_sha256_mode() -> None:
    errors = validate_payload(base_summary_payload(), payload_sha256_mode="bad")
    assert any("payload_sha256_mode must be one of: strict,off" in e for e in errors)
    assert any(f"[{ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_normalizes_mode_values_case_insensitively() -> None:
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "yellow"
    assert validate_payload(payload, schema_mode="COMPATIBLE", payload_sha256_mode="OFF") == []
