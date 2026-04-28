#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from scripts.event_bus_smoke_gh_constants import (
    ALLOWED_GH_RUN_CONCLUSIONS_SET,
    GH_TRIGGER_AUDIT_SOURCE,
)
from scripts.event_bus_smoke_error_codes import (
    ERR_GH_TRIGGER_AGE_MAX_EXCEEDED,
    ERR_GH_TRIGGER_BASE_URL_INVALID,
    ERR_GH_TRIGGER_COMPLETED_AT_ORDER_INVALID,
    ERR_GH_TRIGGER_COMPLETED_AT_TYPE_INVALID,
    ERR_GH_TRIGGER_COMPLETED_AT_POSITIVE_INVALID,
    ERR_GH_TRIGGER_CONCLUSION_FIELD_INVALID,
    ERR_GH_TRIGGER_DECLARED_PATH_MISMATCH,
    ERR_GH_TRIGGER_CONCLUSION_EXPECTED_MISMATCH,
    ERR_GH_TRIGGER_EXPECTED_CONCLUSION_FIELD_INVALID,
    ERR_GH_TRIGGER_EXPECTED_CONCLUSION_INVALID,
    ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_FIELD_INVALID,
    ERR_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION_FIELD_INVALID,
    ERR_GH_TRIGGER_DURATION_CALC_MISMATCH,
    ERR_GH_TRIGGER_DURATION_MAX_EXCEEDED,
    ERR_GH_TRIGGER_DURATION_NON_NEGATIVE_INVALID,
    ERR_GH_TRIGGER_DURATION_TYPE_INVALID,
    ERR_GH_TRIGGER_EVENT_TYPE_INVALID,
    ERR_GH_TRIGGER_EXPECTED_FIELD_MISMATCH,
    ERR_GH_TRIGGER_EXPECTED_TRIGGER_MODE_INVALID,
    ERR_GH_TRIGGER_EXTRA_KEYS,
    ERR_GH_TRIGGER_FILE_SUFFIX_INVALID,
    ERR_GH_TRIGGER_GENERATED_AT_INVALID,
    ERR_GH_TRIGGER_GENERATED_AT_POSITIVE_INVALID,
    ERR_GH_TRIGGER_LIMIT_INVALID,
    ERR_GH_TRIGGER_MISSING_KEYS,
    ERR_GH_TRIGGER_MODE_INVALID,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_MISMATCH,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_FIELD_INVALID,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_FIELD_INVALID,
    ERR_GH_TRIGGER_RUN_URL_RUN_ID_MISMATCH,
    ERR_GH_TRIGGER_RUN_ID_INVALID,
    ERR_GH_TRIGGER_RUN_URL_INVALID,
    ERR_GH_TRIGGER_SCHEMA_VERSION_INVALID,
    ERR_GH_TRIGGER_SCHEMA_MODE_INVALID,
    ERR_GH_TRIGGER_SHA_MODE_MISMATCH,
    ERR_GH_TRIGGER_SOURCE_INVALID,
    ERR_GH_TRIGGER_STALE_THRESHOLD_FIELD_INVALID,
    ERR_GH_TRIGGER_THRESHOLD_INVALID,
    ERR_GH_TRIGGER_TRIGGER_INPUTS_AUDIT_FILE_INVALID,
    ERR_GH_TRIGGER_WORKFLOW_INVALID,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_INVALID,
    ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_INVALID,
)
from scripts.event_bus_smoke_gh_contract_keys import GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS
from scripts.event_bus_smoke_json_integrity import canonical_json_sha256
from scripts.event_bus_smoke_gh_trigger_audit_arg_map import (
    add_base_arguments,
    build_validate_payload_kwargs,
    add_expected_field_arguments,
    add_threshold_arguments,
)

EXPECTED_KEYS = set(GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS)
ALLOWED_AUDIT_SOURCES = {GH_TRIGGER_AUDIT_SOURCE}
MSG_EXPECTED_SCHEMA_VERSION_INVALID = "expected_schema_version must be a positive integer"


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_int_not_bool(value: Any) -> bool:
    return _is_int_not_bool(value) and value > 0


def _with_code(code: str, message: str) -> str:
    return f"[{code}] {message}"


def _is_positive_int_str(value: Any) -> bool:
    return isinstance(value, str) and value.isdigit() and int(value) > 0


def _is_non_negative_int_str(value: Any) -> bool:
    return isinstance(value, str) and value.isdigit()


def _is_positive_int_token(value: Any) -> bool:
    return isinstance(value, str) and value.isdigit() and int(value) > 0


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and re.match(r"^https?://[^\s]+$", value) is not None


def _is_workflow_filename(value: Any) -> bool:
    return isinstance(value, str) and re.match(r"^[^/\\]+\.(yml|yaml)$", value) is not None


def _is_valid_file_suffix(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value == "":
        return True
    return len(value) <= 64 and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _url_tail_matches_run_id(run_url: Any, run_id: Any) -> bool:
    if not isinstance(run_url, str) or not isinstance(run_id, str) or not run_id:
        return False
    cleaned = run_url.rstrip("/")
    return cleaned.endswith(f"/actions/runs/{run_id}")


def _validate_payload_sha256(payload: Dict[str, Any], errors: List[str]) -> None:
    digest = payload.get("payload_sha256")
    if not isinstance(digest, str) or not digest:
        return
    core_payload = dict(payload)
    core_payload.pop("payload_sha256", None)
    expected = canonical_json_sha256(core_payload)
    if digest != expected:
        errors.append(_with_code(ERR_GH_TRIGGER_PAYLOAD_SHA256_MISMATCH, "payload_sha256 mismatch"))


def _validate_schema_config(expected_schema_version: Any, schema_mode: Any) -> tuple[int | None, str | None, List[str]]:
    errors: List[str] = []
    if isinstance(expected_schema_version, bool):
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SCHEMA_VERSION_INVALID,
            )
        )
        return None, None, errors
    try:
        expected_schema_version = int(expected_schema_version)
    except (TypeError, ValueError):
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SCHEMA_VERSION_INVALID,
            )
        )
        return None, None, errors
    if expected_schema_version <= 0:
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_INVALID,
                MSG_EXPECTED_SCHEMA_VERSION_INVALID,
            )
        )
        return None, None, errors
    schema_mode = str(schema_mode).strip().lower()
    if schema_mode not in {"strict", "compatible"}:
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_SCHEMA_MODE_INVALID,
                "schema_mode must be one of: strict,compatible",
            )
        )
        return None, None, errors
    return expected_schema_version, schema_mode, errors


def _validate_requested_modes(
    payload_sha256_mode: Any,
    expected_trigger_mode: Any,
) -> tuple[str | None, str | None, List[str]]:
    errors: List[str] = []
    payload_sha256_mode = str(payload_sha256_mode).strip().lower()
    if payload_sha256_mode not in {"strict", "off"}:
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_INVALID,
                "payload_sha256_mode must be one of: strict,off",
            )
        )
        return None, None, errors
    expected_trigger_mode = str(expected_trigger_mode).strip().lower()
    if expected_trigger_mode and expected_trigger_mode not in {"strict", "compatible"}:
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_EXPECTED_TRIGGER_MODE_INVALID,
                "expected_trigger_mode must be one of: strict,compatible or empty",
            )
        )
        return None, None, errors
    return payload_sha256_mode, expected_trigger_mode, errors


def _validate_declared_keys(payload: Dict[str, Any], errors: List[str]) -> None:
    actual_keys = set(payload.keys())
    missing = sorted(EXPECTED_KEYS - actual_keys)
    extra = sorted(actual_keys - EXPECTED_KEYS)
    if missing:
        errors.append(_with_code(ERR_GH_TRIGGER_MISSING_KEYS, "missing keys: " + ",".join(missing)))
    if extra:
        errors.append(_with_code(ERR_GH_TRIGGER_EXTRA_KEYS, "extra keys: " + ",".join(extra)))


def _build_field_checks(
    payload: Dict[str, Any], schema_version_ok: bool, schema_version_msg: str
) -> list[tuple[Any, ...]]:
    return [
        (schema_version_ok, ERR_GH_TRIGGER_SCHEMA_VERSION_INVALID, schema_version_msg),
        (_is_int_not_bool(payload.get("generated_at_ms")), ERR_GH_TRIGGER_GENERATED_AT_INVALID, "generated_at_ms must be int"),
        (payload.get("source") in ALLOWED_AUDIT_SOURCES, ERR_GH_TRIGGER_SOURCE_INVALID, "source must be supported audit writer"),
        (_is_workflow_filename(payload.get("workflow")), ERR_GH_TRIGGER_WORKFLOW_INVALID, "workflow must be yml/yaml filename"),
        (payload.get("mode") in {"strict", "compatible"}, ERR_GH_TRIGGER_MODE_INVALID, "mode must be strict|compatible"),
        (_is_http_url(payload.get("base_url")), ERR_GH_TRIGGER_BASE_URL_INVALID, "base_url must be http(s) URL"),
        (_is_non_empty_str(payload.get("event_type")), ERR_GH_TRIGGER_EVENT_TYPE_INVALID, "event_type must be non-empty string"),
        (_is_positive_int_str(payload.get("limit")), ERR_GH_TRIGGER_LIMIT_INVALID, "limit must be positive integer string"),
        (
            _is_positive_int_str(payload.get("expected_schema_version")),
            ERR_GH_TRIGGER_EXPECTED_SCHEMA_VERSION_FIELD_INVALID,
            "expected_schema_version must be positive integer string",
        ),
        (
            _is_positive_int_str(payload.get("expected_summary_schema_version")),
            ERR_GH_TRIGGER_EXPECTED_SUMMARY_SCHEMA_VERSION_FIELD_INVALID,
            "expected_summary_schema_version must be positive integer string",
        ),
        (
            payload.get("expected_conclusion") in ALLOWED_GH_RUN_CONCLUSIONS_SET,
            ERR_GH_TRIGGER_EXPECTED_CONCLUSION_FIELD_INVALID,
            "expected_conclusion must be valid GitHub run conclusion",
        ),
        (
            payload.get("payload_sha256_mode") in {"strict", "off"},
            ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_FIELD_INVALID,
            "payload_sha256_mode must be strict|off",
        ),
        (
            _is_non_negative_int_str(payload.get("result_file_stale_threshold_ms")),
            ERR_GH_TRIGGER_STALE_THRESHOLD_FIELD_INVALID,
            "result_file_stale_threshold_ms must be non-negative integer string",
        ),
        (
            _is_valid_file_suffix(payload.get("file_suffix")),
            ERR_GH_TRIGGER_FILE_SUFFIX_INVALID,
            "file_suffix is invalid (allowed [A-Za-z0-9._-], max 64)",
        ),
        (
            _is_non_empty_str(payload.get("trigger_inputs_audit_file")),
            ERR_GH_TRIGGER_TRIGGER_INPUTS_AUDIT_FILE_INVALID,
            "trigger_inputs_audit_file must be non-empty string",
        ),
        (_is_positive_int_token(payload.get("run_id")), ERR_GH_TRIGGER_RUN_ID_INVALID, "run_id must be positive integer string"),
        (_is_http_url(payload.get("run_url")), ERR_GH_TRIGGER_RUN_URL_INVALID, "run_url must be http(s) URL"),
        (
            payload.get("conclusion") in ALLOWED_GH_RUN_CONCLUSIONS_SET,
            ERR_GH_TRIGGER_CONCLUSION_FIELD_INVALID,
            "conclusion must be valid GitHub run conclusion",
        ),
        (_is_int_not_bool(payload.get("completed_at_ms")), ERR_GH_TRIGGER_COMPLETED_AT_TYPE_INVALID, "completed_at_ms must be int"),
        (_is_int_not_bool(payload.get("duration_ms")), ERR_GH_TRIGGER_DURATION_TYPE_INVALID, "duration_ms must be int"),
        (
            _is_non_empty_str(payload.get("payload_sha256")),
            ERR_GH_TRIGGER_PAYLOAD_SHA256_FIELD_INVALID,
            "payload_sha256 must be non-empty string",
        ),
    ]


def _validate_time_consistency(payload: Dict[str, Any], errors: List[str]) -> None:
    generated_at_ms = payload.get("generated_at_ms")
    if _is_int_not_bool(generated_at_ms) and generated_at_ms <= 0:
        errors.append(_with_code(ERR_GH_TRIGGER_GENERATED_AT_POSITIVE_INVALID, "generated_at_ms must be > 0"))
    completed_at_ms = payload.get("completed_at_ms")
    if _is_int_not_bool(completed_at_ms) and completed_at_ms <= 0:
        errors.append(_with_code(ERR_GH_TRIGGER_COMPLETED_AT_POSITIVE_INVALID, "completed_at_ms must be > 0"))
    duration_ms = payload.get("duration_ms")
    if _is_int_not_bool(duration_ms) and duration_ms < 0:
        errors.append(_with_code(ERR_GH_TRIGGER_DURATION_NON_NEGATIVE_INVALID, "duration_ms must be >= 0"))
    if _is_int_not_bool(generated_at_ms) and _is_int_not_bool(completed_at_ms) and completed_at_ms < generated_at_ms:
        errors.append(
            _with_code(ERR_GH_TRIGGER_COMPLETED_AT_ORDER_INVALID, "completed_at_ms must be >= generated_at_ms")
        )
    if (
        _is_int_not_bool(generated_at_ms)
        and _is_int_not_bool(completed_at_ms)
        and _is_int_not_bool(duration_ms)
        and duration_ms != completed_at_ms - generated_at_ms
    ):
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_DURATION_CALC_MISMATCH,
                "duration_ms must equal completed_at_ms - generated_at_ms",
            )
        )
    conclusion = payload.get("conclusion")
    expected_conclusion = payload.get("expected_conclusion")
    if isinstance(conclusion, str) and isinstance(expected_conclusion, str) and expected_conclusion:
        if conclusion != expected_conclusion:
            errors.append(
                _with_code(
                    ERR_GH_TRIGGER_CONCLUSION_EXPECTED_MISMATCH,
                    "conclusion must equal expected_conclusion",
                )
            )


def _validate_cli_consistency(
    payload: Dict[str, Any],
    input_path: Path,
    payload_sha256_mode: str,
) -> List[str]:
    errors: List[str] = []
    declared_sha_mode = payload.get("payload_sha256_mode")
    if isinstance(declared_sha_mode, str) and declared_sha_mode and declared_sha_mode != payload_sha256_mode:
        errors.append(
            _with_code(
                ERR_GH_TRIGGER_SHA_MODE_MISMATCH,
                "payload_sha256_mode in payload must match --payload-sha256-mode",
            )
        )
    declared_path = payload.get("trigger_inputs_audit_file")
    if isinstance(declared_path, str) and declared_path:
        normalized_declared = os.path.realpath(declared_path)
        normalized_input = os.path.realpath(str(input_path))
        if normalized_declared != normalized_input:
            errors.append(
                _with_code(
                    ERR_GH_TRIGGER_DECLARED_PATH_MISMATCH,
                    "trigger_inputs_audit_file must match --input path",
                )
            )
    return errors


def _validate_run_link_consistency(payload: Dict[str, Any], errors: List[str]) -> None:
    run_id = payload.get("run_id")
    run_url = payload.get("run_url")
    if isinstance(run_id, str) and run_id and isinstance(run_url, str) and run_url:
        if not _url_tail_matches_run_id(run_url, run_id):
            errors.append(
                _with_code(
                    ERR_GH_TRIGGER_RUN_URL_RUN_ID_MISMATCH,
                    "run_url must match .../actions/runs/{run_id}",
                )
            )


def _build_schema_version_rule(
    payload: Dict[str, Any], expected_schema_version: int, schema_mode: str
) -> tuple[bool, str]:
    schema_version = payload.get("schema_version")
    schema_version_ok = (
        _is_positive_int_not_bool(schema_version)
        and (schema_version == expected_schema_version if schema_mode == "strict" else schema_version <= expected_schema_version)
    )
    schema_version_msg = (
        f"schema_version must be {expected_schema_version}"
        if schema_mode == "strict"
        else f"schema_version must be <= {expected_schema_version} and > 0"
    )
    return schema_version_ok, schema_version_msg


def _validate_expected_field(payload: Dict[str, Any], errors: List[str], key: str, expected: str, err_msg: str) -> None:
    if not expected:
        return
    actual = payload.get(key)
    if isinstance(actual, str) and actual != expected:
        errors.append(_with_code(ERR_GH_TRIGGER_EXPECTED_FIELD_MISMATCH, err_msg))


def _validate_expected_context(
    payload: Dict[str, Any],
    errors: List[str],
    expected_trigger_mode: str,
    expected_workflow: str,
    expected_base_url: str,
    expected_event_type: str,
) -> None:
    _validate_expected_field(
        payload, errors, "mode", expected_trigger_mode, "mode in payload must match --expected-trigger-mode"
    )
    _validate_expected_field(
        payload, errors, "workflow", expected_workflow, "workflow in payload must match --expected-workflow"
    )
    _validate_expected_field(
        payload, errors, "base_url", expected_base_url, "base_url in payload must match --expected-base-url"
    )
    _validate_expected_field(
        payload, errors, "event_type", expected_event_type, "event_type in payload must match --expected-event-type"
    )


def _validate_named_expectations(
    payload: Dict[str, Any],
    errors: List[str],
    expected_limit: str,
    expected_result_file_stale_threshold_ms: str,
    expected_summary_schema_version: str,
    expected_result_schema_version: str,
    expected_file_suffix: str,
    expected_conclusion: str,
) -> None:
    _validate_expected_field(payload, errors, "limit", expected_limit, "limit in payload must match --expected-limit")
    _validate_expected_field(
        payload,
        errors,
        "result_file_stale_threshold_ms",
        expected_result_file_stale_threshold_ms,
        "result_file_stale_threshold_ms in payload must match --expected-result-file-stale-threshold-ms",
    )
    _validate_expected_field(
        payload,
        errors,
        "expected_summary_schema_version",
        expected_summary_schema_version,
        "expected_summary_schema_version in payload must match --expected-summary-schema-version",
    )
    _validate_expected_field(
        payload,
        errors,
        "expected_schema_version",
        expected_result_schema_version,
        "expected_schema_version in payload must match --expected-result-schema-version",
    )
    _validate_expected_field(
        payload,
        errors,
        "file_suffix",
        expected_file_suffix,
        "file_suffix in payload must match --expected-file-suffix",
    )
    _validate_expected_field(
        payload,
        errors,
        "conclusion",
        expected_conclusion,
        "conclusion in payload must match --expected-conclusion",
    )


def _normalize_optional_threshold(value: Any, label: str) -> tuple[int | None, List[str]]:
    if value is None:
        return None, []
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, [_with_code(ERR_GH_TRIGGER_THRESHOLD_INVALID, f"{label} must be a non-negative integer")]
    if parsed < 0:
        return None, [_with_code(ERR_GH_TRIGGER_THRESHOLD_INVALID, f"{label} must be a non-negative integer")]
    return parsed, []


def _prepare_expected_inputs(
    expected_workflow: str,
    expected_limit: str,
    expected_result_file_stale_threshold_ms: str,
    expected_summary_schema_version: str,
    expected_result_schema_version: str,
    expected_file_suffix: str,
    max_duration_ms: Any,
    legacy_expected: Dict[str, str],
) -> tuple[Dict[str, Any], List[str]]:
    prepared = {
        "expected_workflow": str(expected_workflow).strip(),
        "expected_base_url": str(legacy_expected.get("expected_base_url", "")).strip(),
        "expected_event_type": str(legacy_expected.get("expected_event_type", "")).strip(),
        "expected_limit": str(expected_limit).strip(),
        "expected_result_file_stale_threshold_ms": str(expected_result_file_stale_threshold_ms).strip(),
        "expected_summary_schema_version": str(expected_summary_schema_version).strip(),
        "expected_result_schema_version": str(expected_result_schema_version).strip(),
        "expected_file_suffix": str(expected_file_suffix),
        "expected_conclusion": str(legacy_expected.get("expected_conclusion", "")).strip(),
    }
    max_age_ms = legacy_expected.get("max_age_ms")
    normalized_duration, duration_err = _normalize_optional_threshold(max_duration_ms, "max_duration_ms")
    if duration_err:
        return {}, duration_err
    normalized_age, age_err = _normalize_optional_threshold(max_age_ms, "max_age_ms")
    if age_err:
        return {}, age_err
    prepared["max_duration_ms"] = normalized_duration
    prepared["max_age_ms"] = normalized_age
    return prepared, []


def _validate_runtime_thresholds(
    payload: Dict[str, Any],
    errors: List[str],
    max_duration_ms: int | None,
    max_age_ms: int | None,
) -> None:
    if max_duration_ms is not None:
        duration_ms = payload.get("duration_ms")
        if _is_int_not_bool(duration_ms) and duration_ms > max_duration_ms:
            errors.append(
                _with_code(ERR_GH_TRIGGER_DURATION_MAX_EXCEEDED, "duration_ms in payload must be <= --max-duration-ms")
            )
    if max_age_ms is not None:
        completed_at_ms = payload.get("completed_at_ms")
        if _is_int_not_bool(completed_at_ms):
            age_ms = max(int(time.time() * 1000) - completed_at_ms, 0)
            if age_ms > max_age_ms:
                errors.append(_with_code(ERR_GH_TRIGGER_AGE_MAX_EXCEEDED, "audit age must be <= --max-age-ms"))


def validate_payload(
    payload: Dict[str, Any],
    payload_sha256_mode: str = "strict",
    expected_schema_version: int = 1,
    schema_mode: str = "strict",
    expected_trigger_mode: str = "",
    expected_workflow: str = "",
    expected_limit: str = "",
    expected_result_file_stale_threshold_ms: str = "",
    expected_summary_schema_version: str = "",
    expected_result_schema_version: str = "",
    expected_file_suffix: str = "",
    max_duration_ms: int | None = None,
    **legacy_expected: str,
) -> List[str]:
    expected_schema_version, schema_mode, schema_config_errors = _validate_schema_config(
        expected_schema_version, schema_mode
    )
    if schema_config_errors:
        return schema_config_errors
    payload_sha256_mode, expected_trigger_mode, mode_errors = _validate_requested_modes(
        payload_sha256_mode, expected_trigger_mode
    )
    if mode_errors:
        return mode_errors
    prepared, prepared_err = _prepare_expected_inputs(
        expected_workflow,
        expected_limit,
        expected_result_file_stale_threshold_ms,
        expected_summary_schema_version,
        expected_result_schema_version,
        expected_file_suffix,
        max_duration_ms,
        legacy_expected,
    )
    if prepared_err:
        return prepared_err
    expected_conclusion = str(legacy_expected.get("expected_conclusion", "")).strip()
    if expected_conclusion and expected_conclusion not in ALLOWED_GH_RUN_CONCLUSIONS_SET:
        return [
            _with_code(
                ERR_GH_TRIGGER_EXPECTED_CONCLUSION_INVALID,
                "expected_conclusion must be one of supported GitHub run conclusions",
            )
        ]
    prepared["expected_conclusion"] = expected_conclusion
    errors: List[str] = []
    _validate_declared_keys(payload, errors)
    schema_version_ok, schema_version_msg = _build_schema_version_rule(payload, expected_schema_version, schema_mode)
    checks = _build_field_checks(payload, schema_version_ok, schema_version_msg)
    for check in checks:
        if len(check) == 3:
            ok, code, msg = check
            if not ok:
                errors.append(_with_code(str(code), str(msg)))
            continue
        ok, msg = check
        if not ok:
            errors.append(str(msg))
    _validate_run_link_consistency(payload, errors)
    _validate_time_consistency(payload, errors)
    _validate_expected_context(
        payload,
        errors,
        expected_trigger_mode,
        prepared["expected_workflow"],
        prepared["expected_base_url"],
        prepared["expected_event_type"],
    )
    _validate_named_expectations(
        payload,
        errors,
        prepared["expected_limit"],
        prepared["expected_result_file_stale_threshold_ms"],
        prepared["expected_summary_schema_version"],
        prepared["expected_result_schema_version"],
        prepared["expected_file_suffix"],
        prepared["expected_conclusion"],
    )
    _validate_runtime_thresholds(payload, errors, prepared["max_duration_ms"], prepared["max_age_ms"])
    if payload_sha256_mode == "strict":
        _validate_payload_sha256(payload, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EventBus GH trigger inputs audit JSON contract")
    add_base_arguments(parser)
    add_expected_field_arguments(parser)
    add_threshold_arguments(parser)
    args = parser.parse_args()
    path = Path(args.input)
    if not path.exists():
        print(f"[ERR] trigger inputs audit file not found: {path}")
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERR] failed to parse JSON: {exc}")
        return 2
    if not isinstance(payload, dict):
        print("[ERR] root JSON value must be object")
        return 2
    validate_kwargs = build_validate_payload_kwargs(args)
    errors = validate_payload(payload, **validate_kwargs)
    errors.extend(_validate_cli_consistency(payload, path, args.payload_sha256_mode))
    if errors:
        print("[ERR] gh trigger inputs audit contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("[OK] gh trigger inputs audit contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
