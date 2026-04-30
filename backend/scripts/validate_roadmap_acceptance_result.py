#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_SCHEMA_VERSION = 1


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number_not_bool(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_gate_threshold(name: str, value: Any, errors: List[str]) -> None:
    if value is None:
        return
    if not _is_number_not_bool(value):
        errors.append(f"release_gate.{name} must be number or null")
        return
    if float(value) < 0.0 or float(value) > 1.0:
        errors.append(f"release_gate.{name} must be in range 0..1")


def _validate_base_fields(payload: Dict[str, Any], expected_schema_version: int, errors: List[str]) -> None:
    if payload.get("schema_version") != expected_schema_version:
        errors.append(f"schema_version must be {expected_schema_version}")
    if not _is_int_not_bool(payload.get("generated_at_ms")) or int(payload.get("generated_at_ms", 0)) <= 0:
        errors.append("generated_at_ms must be positive int")
    if not isinstance(payload.get("ok"), bool):
        errors.append("ok must be bool")


def _validate_release_gate(payload: Dict[str, Any], errors: List[str]) -> None:
    release_gate = payload.get("release_gate")
    if not isinstance(release_gate, dict):
        errors.append("release_gate must be object")
        return

    if not isinstance(release_gate.get("require_go"), bool):
        errors.append("release_gate.require_go must be bool")
    _validate_gate_threshold("min_readiness_avg", release_gate.get("min_readiness_avg"), errors)
    _validate_gate_threshold("max_lowest_readiness_score", release_gate.get("max_lowest_readiness_score"), errors)


def _validate_success_payload(payload: Dict[str, Any], errors: List[str]) -> None:
    if payload.get("latest_go_no_go") not in {"go", "no_go"}:
        errors.append("latest_go_no_go must be go|no_go when ok==true")
    if not isinstance(payload.get("phase_readiness_lowest"), str):
        errors.append("phase_readiness_lowest must be string when ok==true")
    if not _is_number_not_bool(payload.get("phase_gate_score")):
        errors.append("phase_gate_score must be number when ok==true")
    if not _is_number_not_bool(payload.get("phase_readiness_avg")):
        errors.append("phase_readiness_avg must be number when ok==true")
    if not _is_number_not_bool(payload.get("north_star_score")):
        errors.append("north_star_score must be number when ok==true")


def _validate_failure_payload(payload: Dict[str, Any], errors: List[str]) -> None:
    if not isinstance(payload.get("error"), str) or not payload.get("error"):
        errors.append("error must be non-empty string when ok==false")


def validate_payload(payload: Dict[str, Any], expected_schema_version: int = DEFAULT_SCHEMA_VERSION) -> List[str]:
    errors: List[str] = []
    _validate_base_fields(payload, expected_schema_version, errors)
    _validate_release_gate(payload, errors)

    ok_value = payload.get("ok")
    if ok_value is True:
        _validate_success_payload(payload, errors)
    elif ok_value is False:
        _validate_failure_payload(payload, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate roadmap acceptance result JSON contract")
    parser.add_argument("--input", required=True, help="Path to roadmap acceptance result JSON")
    parser.add_argument(
        "--expected-schema-version",
        type=int,
        default=DEFAULT_SCHEMA_VERSION,
        help=f"Expected schema_version value (default: {DEFAULT_SCHEMA_VERSION})",
    )
    args = parser.parse_args()

    if int(args.expected_schema_version) <= 0:
        print("[ERR] expected-schema-version must be a positive integer")
        return 2

    path = Path(args.input)
    if not path.exists():
        print(f"[ERR] result file not found: {path}")
        return 2

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] failed to parse JSON: {exc}")
        return 2

    if not isinstance(payload, dict):
        print("[ERR] root JSON value must be object")
        return 2

    errors = validate_payload(payload, expected_schema_version=int(args.expected_schema_version))
    if errors:
        print("[ERR] contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("[OK] roadmap acceptance result contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
