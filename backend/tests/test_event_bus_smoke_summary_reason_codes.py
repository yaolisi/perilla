from __future__ import annotations

from scripts.event_bus_smoke_summary_reason_codes import (
    REASON_ALL_CHECKS_OK,
    REASON_REGISTRY_DEGRADED,
    REASON_SUMMARY_PAYLOAD_KEY_MISMATCH,
    is_allowed_health_reason_code,
)


def test_summary_reason_code_constants_are_stable() -> None:
    assert REASON_ALL_CHECKS_OK == "all_checks_ok"
    assert REASON_REGISTRY_DEGRADED == "registry:unknown_reason_code_detected"
    assert REASON_SUMMARY_PAYLOAD_KEY_MISMATCH == "summary_payload_key_mismatch"


def test_is_allowed_health_reason_code_supports_expected_patterns() -> None:
    assert is_allowed_health_reason_code(REASON_ALL_CHECKS_OK) is True
    assert is_allowed_health_reason_code(REASON_REGISTRY_DEGRADED) is True
    assert is_allowed_health_reason_code(REASON_SUMMARY_PAYLOAD_KEY_MISMATCH) is True
    assert is_allowed_health_reason_code("preflight:missing_required_files") is True
    assert is_allowed_health_reason_code("contract:schema_version_mismatch") is True
    assert is_allowed_health_reason_code("unknown_code") is False
