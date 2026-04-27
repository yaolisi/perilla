from __future__ import annotations

from scripts.event_bus_smoke_summary_keys import (
    KEY_CONTRACT_CHECK,
    KEY_CONTRACT_REASON_CODE,
    KEY_CONTRACT_REASON_KNOWN,
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_HEALTH,
    KEY_HEALTH_REASON,
    KEY_HEALTH_REASON_CODES,
    KEY_LOG_FILE,
    KEY_LOG_FILE_EXISTS,
    KEY_PAYLOAD_SHA256,
    KEY_PREFLIGHT_CHECK,
    KEY_PREFLIGHT_REASON,
    KEY_PREFLIGHT_REASON_KNOWN,
    KEY_RESULT_FILE,
    KEY_RESULT_FILE_EXISTS,
    KEY_RESULT_GENERATED_AT_MS,
    KEY_RESULT_SCHEMA_VERSION,
    SUMMARY_PAYLOAD_KEYS_IN_ORDER,
    KEY_SUMMARY_SCHEMA_VERSION,
)


def test_summary_keys_contract_values_are_stable() -> None:
    assert KEY_SUMMARY_SCHEMA_VERSION == "summary_schema_version"
    assert KEY_HEALTH == "health"
    assert KEY_HEALTH_REASON == "health_reason"
    assert KEY_HEALTH_REASON_CODES == "health_reason_codes"
    assert KEY_PREFLIGHT_CHECK == "preflight_contract_check"
    assert KEY_PREFLIGHT_REASON == "preflight_contract_check_reason"
    assert KEY_PREFLIGHT_REASON_KNOWN == "preflight_reason_code_known"
    assert KEY_CONTRACT_CHECK == "contract_check"
    assert KEY_CONTRACT_REASON_CODE == "contract_check_reason_code"
    assert KEY_CONTRACT_REASON_KNOWN == "contract_reason_code_known"
    assert KEY_RESULT_SCHEMA_VERSION == "result_schema_version"
    assert KEY_RESULT_GENERATED_AT_MS == "result_generated_at_ms"
    assert KEY_RESULT_FILE == "result_file"
    assert KEY_RESULT_FILE_EXISTS == "result_file_exists"
    assert KEY_LOG_FILE == "log_file"
    assert KEY_LOG_FILE_EXISTS == "log_file_exists"
    assert KEY_CONTRACT_GUARD_LOG_FILE == "contract_guard_log_file"
    assert KEY_CONTRACT_GUARD_LOG_FILE_EXISTS == "contract_guard_log_file_exists"
    assert KEY_CONTRACT_GUARD_SECTIONS_SEEN == "contract_guard_sections_seen"
    assert KEY_CONTRACT_GUARD_STATUS == "contract_guard_status"
    assert KEY_PAYLOAD_SHA256 == "payload_sha256"


def test_summary_payload_keys_order_covers_all_contract_keys() -> None:
    expected = [
        KEY_SUMMARY_SCHEMA_VERSION,
        KEY_HEALTH,
        KEY_HEALTH_REASON,
        KEY_HEALTH_REASON_CODES,
        KEY_PREFLIGHT_CHECK,
        KEY_PREFLIGHT_REASON,
        KEY_PREFLIGHT_REASON_KNOWN,
        KEY_CONTRACT_CHECK,
        KEY_CONTRACT_REASON_CODE,
        KEY_CONTRACT_REASON_KNOWN,
        KEY_RESULT_SCHEMA_VERSION,
        KEY_RESULT_GENERATED_AT_MS,
        KEY_RESULT_FILE,
        KEY_RESULT_FILE_EXISTS,
        KEY_LOG_FILE,
        KEY_LOG_FILE_EXISTS,
        KEY_CONTRACT_GUARD_LOG_FILE,
        KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
        KEY_CONTRACT_GUARD_SECTIONS_SEEN,
        KEY_CONTRACT_GUARD_STATUS,
        KEY_PAYLOAD_SHA256,
    ]
    assert SUMMARY_PAYLOAD_KEYS_IN_ORDER == expected


def test_summary_payload_keys_order_is_unique_and_non_empty() -> None:
    assert SUMMARY_PAYLOAD_KEYS_IN_ORDER
    assert len(SUMMARY_PAYLOAD_KEYS_IN_ORDER) == len(set(SUMMARY_PAYLOAD_KEYS_IN_ORDER))
    assert all(isinstance(key, str) and key.strip() for key in SUMMARY_PAYLOAD_KEYS_IN_ORDER)
