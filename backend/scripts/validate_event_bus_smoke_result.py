#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

EXPECTED_SCHEMA_VERSION = 1
MAX_STEP_DETAIL_LENGTH = 2000
ERR_EXPECTED_SCHEMA_VERSION = "expected_schema_version must be a positive integer"


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_step(step: Any, idx: int, errors: List[str]) -> None:
    if not isinstance(step, dict):
        errors.append(f"steps[{idx}] must be object")
        return
    if not isinstance(step.get("name"), str) or not step.get("name"):
        errors.append(f"steps[{idx}].name must be non-empty string")
    elif not step.get("name").strip():
        errors.append(f"steps[{idx}].name must not be blank")
    if not _is_int_not_bool(step.get("status")):
        errors.append(f"steps[{idx}].status must be int")
    elif step.get("status") < 0 or step.get("status") > 599:
        errors.append(f"steps[{idx}].status must be in range 0..599")
    if not isinstance(step.get("ok"), bool):
        errors.append(f"steps[{idx}].ok must be bool")
    if not isinstance(step.get("detail"), str):
        errors.append(f"steps[{idx}].detail must be string")
    elif len(step.get("detail")) > MAX_STEP_DETAIL_LENGTH:
        errors.append(f"steps[{idx}].detail must be <= {MAX_STEP_DETAIL_LENGTH} chars")
    if not _is_int_not_bool(step.get("ts_ms")):
        errors.append(f"steps[{idx}].ts_ms must be int")
    elif step.get("ts_ms") <= 0:
        errors.append(f"steps[{idx}].ts_ms must be > 0")


def _validate_unique_step_names(steps: List[Any], errors: List[str]) -> None:
    names = [s.get("name") for s in steps if isinstance(s, dict) and isinstance(s.get("name"), str)]
    if len(names) != len(set(names)):
        errors.append("steps[].name must be unique")


def _validate_top_level_types(payload: Dict[str, Any], errors: List[str], expected_schema_version: int) -> None:
    checks = [
        (payload.get("schema_version") == expected_schema_version, f"schema_version must be {expected_schema_version}"),
        (_is_int_not_bool(payload.get("generated_at_ms")), "generated_at_ms must be int"),
        (isinstance(payload.get("ok"), bool), "ok must be bool"),
        (isinstance(payload.get("failed_step"), str), "failed_step must be string"),
        (_is_int_not_bool(payload.get("total_steps")), "total_steps must be int"),
        (_is_int_not_bool(payload.get("ok_steps")), "ok_steps must be int"),
        (_is_int_not_bool(payload.get("err_steps")), "err_steps must be int"),
    ]
    for condition, message in checks:
        if not condition:
            errors.append(message)
    schema_version = payload.get("schema_version")
    if _is_int_not_bool(schema_version) and schema_version <= 0:
        errors.append("schema_version must be > 0")
    generated_at_ms = payload.get("generated_at_ms")
    if _is_int_not_bool(generated_at_ms) and generated_at_ms <= 0:
        errors.append("generated_at_ms must be > 0")


def _validate_aggregate_consistency(payload: Dict[str, Any], steps: List[Any], errors: List[str]) -> None:
    total_steps = payload.get("total_steps")
    ok_steps = payload.get("ok_steps")
    err_steps = payload.get("err_steps")
    _validate_non_empty_steps(total_steps, steps, errors)
    if _is_int_not_bool(total_steps) and total_steps != len(steps):
        errors.append("total_steps must equal len(steps)")
    if _is_int_not_bool(ok_steps):
        computed_ok = len([s for s in steps if isinstance(s, dict) and s.get("ok") is True])
        if ok_steps != computed_ok:
            errors.append("ok_steps must equal count(step.ok == true)")
    if _is_int_not_bool(err_steps):
        computed_err = len([s for s in steps if isinstance(s, dict) and s.get("ok") is False])
        if err_steps != computed_err:
            errors.append("err_steps must equal count(step.ok == false)")
    if _is_int_not_bool(ok_steps) and _is_int_not_bool(err_steps) and _is_int_not_bool(total_steps):
        if ok_steps + err_steps != total_steps:
            errors.append("ok_steps + err_steps must equal total_steps")


def _validate_non_empty_steps(total_steps: Any, steps: List[Any], errors: List[str]) -> None:
    if not steps:
        errors.append("steps must not be empty")
    if _is_int_not_bool(total_steps) and total_steps < 1:
        errors.append("total_steps must be >= 1")


def _validate_status_consistency(payload: Dict[str, Any], steps: List[Any], errors: List[str]) -> None:
    ok_value = payload.get("ok")
    failed_step = payload.get("failed_step")
    err_steps = payload.get("err_steps")
    ok_steps = payload.get("ok_steps")
    total_steps = payload.get("total_steps")
    if isinstance(ok_value, bool) and isinstance(failed_step, str):
        if ok_value and failed_step:
            errors.append("failed_step must be empty when ok == true")
        if not ok_value and not failed_step:
            errors.append("failed_step must be non-empty when ok == false")
    _validate_ok_err_step_relation(ok_value, err_steps, errors)
    _validate_ok_total_relation(ok_value, ok_steps, total_steps, errors)
    if isinstance(failed_step, str) and failed_step:
        _validate_failed_step_reference(failed_step, steps, errors)


def _validate_ok_err_step_relation(ok_value: Any, err_steps: Any, errors: List[str]) -> None:
    if not isinstance(ok_value, bool) or not _is_int_not_bool(err_steps):
        return
    if ok_value and err_steps != 0:
        errors.append("err_steps must be 0 when ok == true")
    if not ok_value and err_steps < 1:
        errors.append("err_steps must be >= 1 when ok == false")


def _validate_ok_total_relation(ok_value: Any, ok_steps: Any, total_steps: Any, errors: List[str]) -> None:
    if not isinstance(ok_value, bool) or not _is_int_not_bool(ok_steps) or not _is_int_not_bool(total_steps):
        return
    if ok_value and ok_steps != total_steps:
        errors.append("ok_steps must equal total_steps when ok == true")


def _validate_failed_step_reference(failed_step: str, steps: List[Any], errors: List[str]) -> None:
    step_names = {s.get("name") for s in steps if isinstance(s, dict) and isinstance(s.get("name"), str)}
    if failed_step not in step_names:
        errors.append("failed_step must match one of steps[].name")
        return

    matching_steps = [s for s in steps if isinstance(s, dict) and s.get("name") == failed_step]
    if not any(s.get("ok") is False for s in matching_steps):
        errors.append("failed_step must reference a step with ok == false")

    last_name = steps[-1].get("name") if steps and isinstance(steps[-1], dict) else None
    if failed_step != last_name:
        errors.append("failed_step must equal the last step name")


def _validate_time_consistency(payload: Dict[str, Any], steps: List[Any], errors: List[str]) -> None:
    ts_values = [s.get("ts_ms") for s in steps if isinstance(s, dict) and _is_int_not_bool(s.get("ts_ms"))]
    if len(ts_values) != len(steps):
        return
    if any(ts_values[i] > ts_values[i + 1] for i in range(len(ts_values) - 1)):
        errors.append("steps[].ts_ms must be non-decreasing")
    generated_at_ms = payload.get("generated_at_ms")
    if _is_int_not_bool(generated_at_ms) and ts_values:
        if generated_at_ms < ts_values[-1]:
            errors.append("generated_at_ms must be >= last step ts_ms")


def validate_payload(payload: Dict[str, Any], expected_schema_version: int = EXPECTED_SCHEMA_VERSION) -> List[str]:
    if isinstance(expected_schema_version, bool):
        return [ERR_EXPECTED_SCHEMA_VERSION]
    try:
        expected_schema_version = int(expected_schema_version)
    except (TypeError, ValueError):
        return [ERR_EXPECTED_SCHEMA_VERSION]
    if expected_schema_version <= 0:
        return [ERR_EXPECTED_SCHEMA_VERSION]
    errors: List[str] = []
    _validate_top_level_types(payload, errors, expected_schema_version)

    steps = payload.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be list")
        return errors

    for idx, step in enumerate(steps):
        _validate_step(step, idx, errors)
    _validate_unique_step_names(steps, errors)

    _validate_aggregate_consistency(payload, steps, errors)
    _validate_status_consistency(payload, steps, errors)
    _validate_time_consistency(payload, steps, errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate EventBus smoke result JSON contract")
    parser.add_argument("--input", required=True, help="Path to event-bus-smoke-result.json")
    parser.add_argument(
        "--expected-schema-version",
        type=int,
        default=EXPECTED_SCHEMA_VERSION,
        help=f"Expected schema_version value (default: {EXPECTED_SCHEMA_VERSION})",
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
    except Exception as exc:
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

    print("[OK] smoke result contract validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
