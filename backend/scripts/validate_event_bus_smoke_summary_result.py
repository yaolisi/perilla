#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from scripts.event_bus_smoke_contract_guard_summary import GUARD_SECTIONS, sections_seen_from_status
from scripts.event_bus_smoke_error_codes import (
    ERR_CONTRACT_CHECK_INVALID,
    ERR_CONTRACT_REASON_CODE_INVALID,
    ERR_CONTRACT_REASON_KNOWN_INVALID,
    ERR_GUARD_SEEN_REQUIRES_EMPTY_WHEN_LOG_MISSING,
    ERR_GUARD_LOG_FILE_EXISTS_INVALID,
    ERR_GUARD_LOG_FILE_INVALID,
    ERR_GUARD_SECTIONS_SEEN_ITEM_INVALID,
    ERR_GUARD_SECTIONS_SEEN_DUPLICATES,
    ERR_GUARD_SECTIONS_SEEN_TYPE_INVALID,
    ERR_GUARD_SECTIONS_SEEN_UNSUPPORTED,
    ERR_GUARD_SEEN_STATUS_INCONSISTENT,
    ERR_GUARD_STATUS_REQUIRES_MISSING_WHEN_LOG_MISSING,
    ERR_GUARD_STATUS_TYPE_INVALID,
    ERR_GUARD_STATUS_INVALID_VALUE,
    ERR_GUARD_STATUS_KEY_MISMATCH,
    ERR_HEALTH_INVALID,
    ERR_HEALTH_REASON_CODES_EMPTY,
    ERR_HEALTH_REASON_CODES_ITEM_INVALID,
    ERR_HEALTH_REASON_CODES_MISMATCH,
    ERR_HEALTH_REASON_CODES_TYPE_INVALID,
    ERR_HEALTH_REASON_CODES_UNSUPPORTED,
    ERR_HEALTH_CONTRACT_MISMATCH_MUST_NOT_GREEN,
    ERR_HEALTH_PRECHECK_MISMATCH_REQUIRES_RED,
    ERR_HEALTH_REASON_INVALID,
    ERR_LOG_FILE_EXISTS_INVALID,
    ERR_LOG_FILE_INVALID,
    ERR_PAYLOAD_SHA256_MISSING_OR_INVALID,
    ERR_PAYLOAD_SHA256_MISMATCH,
    ERR_PREFLIGHT_CHECK_INVALID,
    ERR_PREFLIGHT_REASON_INVALID,
    ERR_PREFLIGHT_REASON_KNOWN_INVALID,
    ERR_RESULT_FILE_EXISTS_INVALID,
    ERR_RESULT_FILE_INVALID,
    ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE,
    ERR_RESULT_GENERATED_AT_MS_TYPE_INVALID,
    ERR_RESULT_SCHEMA_VERSION_NON_POSITIVE,
    ERR_RESULT_SCHEMA_VERSION_TYPE_INVALID,
    ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
    ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID,
    ERR_SUMMARY_SCHEMA_MODE_INVALID,
    ERR_SUMMARY_SCHEMA_VERSION_INVALID,
)
from scripts.event_bus_smoke_summary_keys import (
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_CONTRACT_CHECK,
    KEY_CONTRACT_REASON_CODE,
    KEY_CONTRACT_REASON_KNOWN,
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
    KEY_SUMMARY_SCHEMA_VERSION,
)
from scripts.event_bus_smoke_summary_reason_codes import (
    REASON_ALL_CHECKS_OK,
    REASON_REGISTRY_DEGRADED,
    REASON_SUMMARY_PAYLOAD_KEY_MISMATCH,
    is_allowed_health_reason_code,
)
from scripts.event_bus_smoke_json_integrity import canonical_json_dumps, canonical_json_sha256

EXPECTED_SUMMARY_SCHEMA_VERSION = 1
MSG_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID = "expected_summary_schema_version must be a positive integer"


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_positive_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _with_details(message: str, details: Dict[str, Any]) -> str:
    details_json = canonical_json_dumps(details)
    return f"{message} (details={details_json})"


def _with_code(code: str, message: str) -> str:
    return f"[{code}] {message}"


def _validate_top_level(payload: Dict[str, Any], errors: List[str], expected_schema_version: int, schema_mode: str) -> None:
    summary_schema_version = payload.get(KEY_SUMMARY_SCHEMA_VERSION)
    schema_version_valid = (
        _is_positive_int_not_bool(summary_schema_version)
        and (
            summary_schema_version == expected_schema_version
            if schema_mode == "strict"
            else summary_schema_version <= expected_schema_version
        )
    )
    schema_version_msg = (
        f"summary_schema_version must be {expected_schema_version}"
        if schema_mode == "strict"
        else f"summary_schema_version must be <= {expected_schema_version} and > 0"
    )
    checks = [
        (schema_version_valid, ERR_SUMMARY_SCHEMA_VERSION_INVALID, schema_version_msg),
        (payload.get(KEY_HEALTH) in {"green", "yellow", "red"}, ERR_HEALTH_INVALID, "health must be one of: green,yellow,red"),
        (_is_non_empty_str(payload.get(KEY_HEALTH_REASON)), ERR_HEALTH_REASON_INVALID, "health_reason must be non-empty string"),
        (payload.get(KEY_PREFLIGHT_CHECK) in {"ok", "mismatch"}, ERR_PREFLIGHT_CHECK_INVALID, "preflight_contract_check must be one of: ok,mismatch"),
        (_is_non_empty_str(payload.get(KEY_PREFLIGHT_REASON)), ERR_PREFLIGHT_REASON_INVALID, "preflight_contract_check_reason must be non-empty string"),
        (isinstance(payload.get(KEY_PREFLIGHT_REASON_KNOWN), bool), ERR_PREFLIGHT_REASON_KNOWN_INVALID, "preflight_reason_code_known must be bool"),
        (payload.get(KEY_CONTRACT_CHECK) in {"ok", "mismatch"}, ERR_CONTRACT_CHECK_INVALID, "contract_check must be one of: ok,mismatch"),
        (_is_non_empty_str(payload.get(KEY_CONTRACT_REASON_CODE)), ERR_CONTRACT_REASON_CODE_INVALID, "contract_check_reason_code must be non-empty string"),
        (isinstance(payload.get(KEY_CONTRACT_REASON_KNOWN), bool), ERR_CONTRACT_REASON_KNOWN_INVALID, "contract_reason_code_known must be bool"),
        (_is_non_empty_str(payload.get(KEY_RESULT_FILE)), ERR_RESULT_FILE_INVALID, "result_file must be non-empty string"),
        (isinstance(payload.get(KEY_RESULT_FILE_EXISTS), bool), ERR_RESULT_FILE_EXISTS_INVALID, "result_file_exists must be bool"),
        (_is_non_empty_str(payload.get(KEY_LOG_FILE)), ERR_LOG_FILE_INVALID, "log_file must be non-empty string"),
        (isinstance(payload.get(KEY_LOG_FILE_EXISTS), bool), ERR_LOG_FILE_EXISTS_INVALID, "log_file_exists must be bool"),
        (
            _is_non_empty_str(payload.get(KEY_CONTRACT_GUARD_LOG_FILE)),
            ERR_GUARD_LOG_FILE_INVALID,
            "contract_guard_log_file must be non-empty string",
        ),
        (
            isinstance(payload.get(KEY_CONTRACT_GUARD_LOG_FILE_EXISTS), bool),
            ERR_GUARD_LOG_FILE_EXISTS_INVALID,
            "contract_guard_log_file_exists must be bool",
        ),
        (isinstance(payload.get(KEY_CONTRACT_GUARD_SECTIONS_SEEN), list), ERR_GUARD_SECTIONS_SEEN_TYPE_INVALID, "contract_guard_sections_seen must be list"),
        (isinstance(payload.get(KEY_CONTRACT_GUARD_STATUS), dict), ERR_GUARD_STATUS_TYPE_INVALID, "contract_guard_status must be object"),
        (_is_non_empty_str(payload.get(KEY_PAYLOAD_SHA256)), ERR_PAYLOAD_SHA256_MISSING_OR_INVALID, "payload_sha256 must be non-empty string"),
    ]
    for ok, code, msg in checks:
        if not ok:
            errors.append(_with_code(code, msg))


def _validate_reason_codes(payload: Dict[str, Any], errors: List[str]) -> None:
    codes = payload.get(KEY_HEALTH_REASON_CODES)
    if not isinstance(codes, list):
        errors.append(_with_code(ERR_HEALTH_REASON_CODES_TYPE_INVALID, "health_reason_codes must be list"))
        return
    if not codes:
        errors.append(_with_code(ERR_HEALTH_REASON_CODES_EMPTY, "health_reason_codes must not be empty"))
        return
    if not all(_is_non_empty_str(code) for code in codes):
        errors.append(_with_code(ERR_HEALTH_REASON_CODES_ITEM_INVALID, "health_reason_codes[] must be non-empty string"))
    health_reason = payload.get(KEY_HEALTH_REASON)
    if isinstance(health_reason, str):
        expected_codes = [part for part in health_reason.split(",") if part]
        if health_reason == REASON_ALL_CHECKS_OK:
            expected_codes = [REASON_ALL_CHECKS_OK]
        if expected_codes and codes != expected_codes:
            errors.append(
                _with_code(ERR_HEALTH_REASON_CODES_MISMATCH, "health_reason_codes must match parsed health_reason")
            )
    for code in codes:
        if not isinstance(code, str):
            continue
        if not is_allowed_health_reason_code(code):
            errors.append(_with_code(ERR_HEALTH_REASON_CODES_UNSUPPORTED, f"health_reason_codes[] contains unsupported code: {code}"))


def _validate_optional_result_fields(payload: Dict[str, Any], errors: List[str]) -> None:
    result_schema_version = payload.get(KEY_RESULT_SCHEMA_VERSION)
    if result_schema_version is not None:
        if not _is_int_not_bool(result_schema_version):
            errors.append(_with_code(ERR_RESULT_SCHEMA_VERSION_TYPE_INVALID, "result_schema_version must be int or null"))
        elif result_schema_version <= 0:
            errors.append(_with_code(ERR_RESULT_SCHEMA_VERSION_NON_POSITIVE, "result_schema_version must be > 0 when present"))
    result_generated_at_ms = payload.get(KEY_RESULT_GENERATED_AT_MS)
    if result_generated_at_ms is not None:
        if not _is_int_not_bool(result_generated_at_ms):
            errors.append(_with_code(ERR_RESULT_GENERATED_AT_MS_TYPE_INVALID, "result_generated_at_ms must be int or null"))
        elif result_generated_at_ms <= 0:
            errors.append(_with_code(ERR_RESULT_GENERATED_AT_MS_NON_POSITIVE, "result_generated_at_ms must be > 0 when present"))


def _validate_state_consistency(payload: Dict[str, Any], errors: List[str]) -> None:
    health = payload.get(KEY_HEALTH)
    preflight_check = payload.get(KEY_PREFLIGHT_CHECK)
    contract_check = payload.get(KEY_CONTRACT_CHECK)
    health_reason_codes = payload.get(KEY_HEALTH_REASON_CODES)
    if not isinstance(health_reason_codes, list):
        health_reason_codes = []
    has_registry_degraded = "registry:unknown_reason_code_detected" in health_reason_codes
    if preflight_check == "mismatch" and health != "red":
        errors.append(
            _with_code(
                ERR_HEALTH_PRECHECK_MISMATCH_REQUIRES_RED,
                "health must be red when preflight_contract_check == mismatch",
            )
        )
    if preflight_check == "ok" and (contract_check == "mismatch" or has_registry_degraded) and health == "green":
        errors.append(
            _with_code(
                ERR_HEALTH_CONTRACT_MISMATCH_MUST_NOT_GREEN,
                "health must not be green when contract mismatches or registry is degraded",
            )
        )
    _validate_guard_file_existence_consistency(payload, errors)
    _validate_guard_observability_fields(payload, errors)


def _validate_guard_observability_fields(payload: Dict[str, Any], errors: List[str]) -> None:
    guard_sections_seen = payload.get(KEY_CONTRACT_GUARD_SECTIONS_SEEN)
    seen_sections: List[str] | None = None
    if isinstance(guard_sections_seen, list):
        seen_sections = _validate_guard_sections_seen(guard_sections_seen, errors)
    guard_status = payload.get(KEY_CONTRACT_GUARD_STATUS)
    normalized_status: Dict[str, str] | None = None
    if isinstance(guard_status, dict):
        normalized_status = _validate_guard_status_map(guard_status, errors)
    if seen_sections is not None and normalized_status is not None:
        _validate_guard_seen_status_consistency(seen_sections, normalized_status, errors)


def _validate_guard_file_existence_consistency(payload: Dict[str, Any], errors: List[str]) -> None:
    exists = payload.get(KEY_CONTRACT_GUARD_LOG_FILE_EXISTS)
    if not isinstance(exists, bool):
        return
    seen_sections = payload.get(KEY_CONTRACT_GUARD_SECTIONS_SEEN)
    guard_status = payload.get(KEY_CONTRACT_GUARD_STATUS)
    if exists:
        return
    if isinstance(seen_sections, list) and seen_sections:
        errors.append(
            _with_code(
                ERR_GUARD_SEEN_REQUIRES_EMPTY_WHEN_LOG_MISSING,
                "contract_guard_sections_seen must be empty when contract_guard_log_file_exists is false",
            )
        )
    if isinstance(guard_status, dict):
        if any(value != "missing" for value in guard_status.values()):
            errors.append(
                _with_code(
                    ERR_GUARD_STATUS_REQUIRES_MISSING_WHEN_LOG_MISSING,
                    "contract_guard_status values must all be missing when contract_guard_log_file_exists is false",
                )
            )


def _validate_guard_sections_seen(guard_sections_seen: List[Any], errors: List[str]) -> List[str] | None:
    if not all(_is_non_empty_str(item) for item in guard_sections_seen):
        errors.append(
            _with_code(
                ERR_GUARD_SECTIONS_SEEN_ITEM_INVALID,
                "contract_guard_sections_seen[] must be non-empty string",
            )
        )
        return None
    normalized = [str(item) for item in guard_sections_seen]
    counts: Dict[str, int] = {}
    for item in normalized:
        counts[item] = counts.get(item, 0) + 1
    if len(normalized) != len(set(normalized)):
        duplicates = sorted([item for item, count in counts.items() if count > 1])
        errors.append(
            _with_code(
                ERR_GUARD_SECTIONS_SEEN_DUPLICATES,
                _with_details("contract_guard_sections_seen must not contain duplicates", {"duplicates": duplicates}),
            )
        )
        return None
    invalid = sorted([item for item in normalized if item not in GUARD_SECTIONS])
    if invalid:
        errors.append(
            _with_code(
                ERR_GUARD_SECTIONS_SEEN_UNSUPPORTED,
                _with_details("contract_guard_sections_seen contains unsupported section", {"unsupported": invalid}),
            )
        )
        return None
    return normalized


def _validate_guard_status_map(guard_status: Dict[str, Any], errors: List[str]) -> Dict[str, str] | None:
    expected_guard_keys = set(GUARD_SECTIONS)
    actual_guard_keys = set(guard_status.keys())
    if actual_guard_keys != expected_guard_keys:
        missing = sorted(expected_guard_keys - actual_guard_keys)
        extra = sorted(actual_guard_keys - expected_guard_keys)
        errors.append(
            _with_code(
                ERR_GUARD_STATUS_KEY_MISMATCH,
                _with_details(
                    "contract_guard_status must contain all guard sections",
                    {"missing_keys": missing, "extra_keys": extra},
                ),
            )
        )
        return None
    normalized: Dict[str, str] = {}
    for section, value in guard_status.items():
        if section not in expected_guard_keys:
            continue
        if value not in {"seen", "missing"}:
            errors.append(
                _with_code(
                    ERR_GUARD_STATUS_INVALID_VALUE,
                    _with_details(
                        f"contract_guard_status[{section}] must be seen|missing",
                        {"actual": value, "allowed": ["seen", "missing"]},
                    ),
                )
            )
            return None
        normalized[section] = str(value)
    return normalized


def _validate_guard_seen_status_consistency(seen_sections: List[str], guard_status: Dict[str, str], errors: List[str]) -> None:
    expected_seen = sections_seen_from_status(guard_status, sections=GUARD_SECTIONS)
    if seen_sections != expected_seen:
        errors.append(
            _with_code(
                ERR_GUARD_SEEN_STATUS_INCONSISTENT,
                _with_details(
                    "contract_guard_sections_seen must match contract_guard_status order/content",
                    {"expected": expected_seen, "actual": seen_sections},
                ),
            )
        )


def _validate_payload_sha256(payload: Dict[str, Any], errors: List[str]) -> None:
    digest = payload.get(KEY_PAYLOAD_SHA256)
    if not isinstance(digest, str) or not digest:
        return
    core_payload = dict(payload)
    core_payload.pop(KEY_PAYLOAD_SHA256, None)
    expected = canonical_json_sha256(core_payload)
    if digest != expected:
        errors.append(_with_code(ERR_PAYLOAD_SHA256_MISMATCH, "payload_sha256 mismatch"))


def validate_payload(
    payload: Dict[str, Any],
    expected_summary_schema_version: int = EXPECTED_SUMMARY_SCHEMA_VERSION,
    schema_mode: str = "strict",
    payload_sha256_mode: str = "strict",
) -> List[str]:
    if isinstance(expected_summary_schema_version, bool):
        return [
            _with_code(
                ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID,
            )
        ]
    try:
        expected_summary_schema_version = int(expected_summary_schema_version)
    except (TypeError, ValueError):
        return [
            _with_code(
                ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID,
            )
        ]
    if expected_summary_schema_version <= 0:
        return [
            _with_code(
                ERR_SUMMARY_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID,
            )
        ]
    schema_mode = str(schema_mode).strip().lower()
    if schema_mode not in {"strict", "compatible"}:
        return [_with_code(ERR_SUMMARY_SCHEMA_MODE_INVALID, "schema_mode must be one of: strict,compatible")]
    payload_sha256_mode = str(payload_sha256_mode).strip().lower()
    if payload_sha256_mode not in {"strict", "off"}:
        return [
            _with_code(
                ERR_SUMMARY_PAYLOAD_SHA256_MODE_INVALID,
                "payload_sha256_mode must be one of: strict,off",
            )
        ]
    errors: List[str] = []
    _validate_top_level(payload, errors, expected_summary_schema_version, schema_mode)
    _validate_reason_codes(payload, errors)
    _validate_optional_result_fields(payload, errors)
    _validate_state_consistency(payload, errors)
    if payload_sha256_mode == "strict":
        _validate_payload_sha256(payload, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EventBus smoke summary JSON contract")
    parser.add_argument("--input", required=True, help="Path to event-bus-smoke-summary.json")
    parser.add_argument(
        "--expected-summary-schema-version",
        type=int,
        default=EXPECTED_SUMMARY_SCHEMA_VERSION,
        help=f"Expected summary_schema_version value (default: {EXPECTED_SUMMARY_SCHEMA_VERSION})",
    )
    parser.add_argument(
        "--schema-mode",
        choices=["strict", "compatible"],
        default="strict",
        help="Schema validation mode: strict(==) or compatible(<=)",
    )
    parser.add_argument(
        "--payload-sha256-mode",
        choices=["strict", "off"],
        default="strict",
        help="Payload sha256 validation mode: strict(validate) or off(skip)",
    )
    args = parser.parse_args()
    if int(args.expected_summary_schema_version) <= 0:
        print("[ERR] expected-summary-schema-version must be a positive integer")
        return 2
    path = Path(args.input)
    if not path.exists():
        print(f"[ERR] summary file not found: {path}")
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERR] failed to parse JSON: {exc}")
        return 2
    if not isinstance(payload, dict):
        print("[ERR] root JSON value must be object")
        return 2
    errors = validate_payload(
        payload,
        expected_summary_schema_version=int(args.expected_summary_schema_version),
        schema_mode=args.schema_mode,
        payload_sha256_mode=args.payload_sha256_mode,
    )
    if errors:
        print("[ERR] summary contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("[OK] smoke summary contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
