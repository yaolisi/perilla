#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from scripts.event_bus_smoke_error_codes import (
    ERR_GH_SNAPSHOT_BASE_URL_INVALID,
    ERR_GH_SNAPSHOT_EVENT_TYPE_INVALID,
    ERR_GH_SNAPSHOT_EXPECTED_SCHEMA_VERSION_INVALID,
    ERR_GH_SNAPSHOT_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID,
    ERR_GH_SNAPSHOT_EXTRA_KEYS,
    ERR_GH_SNAPSHOT_FILE_SUFFIX_INVALID,
    ERR_GH_SNAPSHOT_GENERATED_AT_POSITIVE_INVALID,
    ERR_GH_SNAPSHOT_GENERATED_AT_TYPE_INVALID,
    ERR_GH_SNAPSHOT_LIMIT_INVALID,
    ERR_GH_SNAPSHOT_MISSING_KEYS,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_FIELD_INVALID,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MISMATCH,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_FIELD_INVALID,
    ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_INVALID,
    ERR_GH_SNAPSHOT_SCHEMA_VERSION_INVALID,
    ERR_GH_SNAPSHOT_SCHEMA_VERSION_POSITIVE_INVALID,
    ERR_GH_SNAPSHOT_SOURCE_INVALID,
    ERR_GH_SNAPSHOT_STALE_THRESHOLD_INVALID,
    ERR_GH_SNAPSHOT_SUMMARY_SCHEMA_MODE_INVALID,
    ERR_GH_SNAPSHOT_WORKFLOW_INVALID,
)
from scripts.event_bus_smoke_gh_contract_keys import GH_INPUTS_SNAPSHOT_EXPECTED_KEYS
from scripts.event_bus_smoke_json_integrity import canonical_json_sha256

EXPECTED_SCHEMA_VERSION = 1


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _with_code(code: str, message: str) -> str:
    return f"[{code}] {message}"


def validate_payload(
    payload: Dict[str, Any],
    expected_schema_version: int = EXPECTED_SCHEMA_VERSION,
    payload_sha256_mode: str = "strict",
) -> List[str]:
    payload_sha256_mode = str(payload_sha256_mode).strip().lower()
    if payload_sha256_mode not in {"strict", "off"}:
        return [_with_code(ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_INVALID, "payload_sha256_mode must be one of: strict,off")]
    errors: List[str] = []
    actual_keys = set(payload.keys())
    missing = sorted(GH_INPUTS_SNAPSHOT_EXPECTED_KEYS - actual_keys)
    extra = sorted(actual_keys - GH_INPUTS_SNAPSHOT_EXPECTED_KEYS)
    if missing:
        errors.append(_with_code(ERR_GH_SNAPSHOT_MISSING_KEYS, "missing keys: " + ",".join(missing)))
    if extra:
        errors.append(_with_code(ERR_GH_SNAPSHOT_EXTRA_KEYS, "extra keys: " + ",".join(extra)))
    checks = [
        (
            payload.get("schema_version") == expected_schema_version,
            ERR_GH_SNAPSHOT_SCHEMA_VERSION_INVALID,
            f"schema_version must be {expected_schema_version}",
        ),
        (isinstance(payload.get("generated_at_ms"), int), ERR_GH_SNAPSHOT_GENERATED_AT_TYPE_INVALID, "generated_at_ms must be int"),
        (_is_non_empty_str(payload.get("source")), ERR_GH_SNAPSHOT_SOURCE_INVALID, "source must be non-empty string"),
        (_is_non_empty_str(payload.get("workflow")), ERR_GH_SNAPSHOT_WORKFLOW_INVALID, "workflow must be non-empty string"),
        (_is_non_empty_str(payload.get("base_url")), ERR_GH_SNAPSHOT_BASE_URL_INVALID, "base_url must be non-empty string"),
        (_is_non_empty_str(payload.get("event_type")), ERR_GH_SNAPSHOT_EVENT_TYPE_INVALID, "event_type must be non-empty string"),
        (_is_non_empty_str(payload.get("limit")), ERR_GH_SNAPSHOT_LIMIT_INVALID, "limit must be non-empty string"),
        (
            _is_non_empty_str(payload.get("expected_schema_version")),
            ERR_GH_SNAPSHOT_EXPECTED_SCHEMA_VERSION_INVALID,
            "expected_schema_version must be non-empty string",
        ),
        (
            _is_non_empty_str(payload.get("expected_summary_schema_version")),
            ERR_GH_SNAPSHOT_EXPECTED_SUMMARY_SCHEMA_VERSION_INVALID,
            "expected_summary_schema_version must be non-empty string",
        ),
        (
            payload.get("summary_schema_mode") in {"strict", "compatible"},
            ERR_GH_SNAPSHOT_SUMMARY_SCHEMA_MODE_INVALID,
            "summary_schema_mode must be strict|compatible",
        ),
        (
            payload.get("payload_sha256_mode") in {"strict", "off"},
            ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MODE_FIELD_INVALID,
            "payload_sha256_mode must be strict|off",
        ),
        (
            _is_non_empty_str(payload.get("result_file_stale_threshold_ms")),
            ERR_GH_SNAPSHOT_STALE_THRESHOLD_INVALID,
            "result_file_stale_threshold_ms must be non-empty string",
        ),
        (isinstance(payload.get("file_suffix"), str), ERR_GH_SNAPSHOT_FILE_SUFFIX_INVALID, "file_suffix must be string"),
        (
            _is_non_empty_str(payload.get("payload_sha256")),
            ERR_GH_SNAPSHOT_PAYLOAD_SHA256_FIELD_INVALID,
            "payload_sha256 must be non-empty string",
        ),
    ]
    for ok, code, msg in checks:
        if not ok:
            errors.append(_with_code(code, msg))
    generated_at_ms = payload.get("generated_at_ms")
    if isinstance(generated_at_ms, int) and generated_at_ms <= 0:
        errors.append(_with_code(ERR_GH_SNAPSHOT_GENERATED_AT_POSITIVE_INVALID, "generated_at_ms must be > 0"))
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, int) and schema_version <= 0:
        errors.append(_with_code(ERR_GH_SNAPSHOT_SCHEMA_VERSION_POSITIVE_INVALID, "schema_version must be > 0"))
    if payload_sha256_mode == "strict":
        _validate_payload_sha256(payload, errors)
    return errors


def _validate_payload_sha256(payload: Dict[str, Any], errors: List[str]) -> None:
    digest = payload.get("payload_sha256")
    if not isinstance(digest, str) or not digest:
        return
    core_payload = dict(payload)
    core_payload.pop("payload_sha256", None)
    expected = canonical_json_sha256(core_payload)
    if digest != expected:
        errors.append(_with_code(ERR_GH_SNAPSHOT_PAYLOAD_SHA256_MISMATCH, "payload_sha256 mismatch"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EventBus GH inputs snapshot JSON contract")
    parser.add_argument("--input", required=True, help="Path to event-bus-smoke-gh-inputs.json")
    parser.add_argument("--expected-schema-version", type=int, default=EXPECTED_SCHEMA_VERSION)
    parser.add_argument(
        "--payload-sha256-mode",
        choices=["strict", "off"],
        default="strict",
        help="Payload sha256 validation mode: strict(validate) or off(skip)",
    )
    args = parser.parse_args()
    if int(args.expected_schema_version) <= 0:
        print("[ERR] expected-schema-version must be a positive integer")
        return 2
    path = Path(args.input)
    if not path.exists():
        print(f"[ERR] snapshot file not found: {path}")
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
        expected_schema_version=int(args.expected_schema_version),
        payload_sha256_mode=args.payload_sha256_mode,
    )
    if errors:
        print("[ERR] gh inputs snapshot contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("[OK] gh inputs snapshot contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
