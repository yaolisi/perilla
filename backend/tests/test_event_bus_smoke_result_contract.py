from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from scripts.validate_event_bus_smoke_result import validate_payload

from tests.repo_paths import repo_run_python


def _run_result_cli(input_path: Path, *extra: str):
    return repo_run_python(
        "backend/scripts/validate_event_bus_smoke_result.py",
        ["--input", str(input_path), *extra],
        capture_output=True,
        text=True,
    )


def _base_payload() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at_ms": 1710000000003,
        "ok": True,
        "failed_step": "",
        "total_steps": 2,
        "ok_steps": 2,
        "err_steps": 0,
        "steps": [
            {"name": "a", "status": 200, "ok": True, "detail": "", "ts_ms": 1710000000001},
            {"name": "b", "status": 200, "ok": True, "detail": "", "ts_ms": 1710000000002},
        ],
    }


def test_validate_payload_accepts_valid_contract() -> None:
    assert validate_payload(_base_payload()) == []


def test_validate_payload_rejects_steps_mismatch() -> None:
    payload = _base_payload()
    payload["ok_steps"] = 1
    errors = validate_payload(payload)
    assert any("ok_steps must equal count(step.ok == true)" in e for e in errors)


def test_validate_payload_rejects_empty_steps_and_zero_total() -> None:
    payload = _base_payload()
    payload["steps"] = []
    payload["total_steps"] = 0
    payload["ok_steps"] = 0
    payload["err_steps"] = 0
    errors = validate_payload(payload)
    assert any("steps must not be empty" in e for e in errors)
    assert any("total_steps must be >= 1" in e for e in errors)


def test_validate_payload_rejects_step_status_out_of_range() -> None:
    payload = _base_payload()
    payload["steps"][0]["status"] = 700
    errors = validate_payload(payload)
    assert any("steps[0].status must be in range 0..599" in e for e in errors)


def test_validate_payload_rejects_non_positive_generated_at_ms() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = 0
    errors = validate_payload(payload)
    assert any("generated_at_ms must be > 0" in e for e in errors)


def test_validate_payload_rejects_bool_step_numeric_fields() -> None:
    payload = _base_payload()
    payload["steps"][0]["status"] = True
    payload["steps"][0]["ts_ms"] = False
    errors = validate_payload(payload)
    assert any("steps[0].status must be int" in e for e in errors)
    assert any("steps[0].ts_ms must be int" in e for e in errors)


def test_validate_payload_rejects_non_positive_step_ts() -> None:
    payload = _base_payload()
    payload["steps"][0]["ts_ms"] = 0
    errors = validate_payload(payload)
    assert any("steps[0].ts_ms must be > 0" in e for e in errors)


def test_validate_payload_rejects_duplicate_step_names() -> None:
    payload = _base_payload()
    payload["steps"][1]["name"] = "a"
    errors = validate_payload(payload)
    assert any("steps[].name must be unique" in e for e in errors)


def test_validate_payload_rejects_blank_step_name() -> None:
    payload = _base_payload()
    payload["steps"][0]["name"] = "   "
    errors = validate_payload(payload)
    assert any("steps[0].name must not be blank" in e for e in errors)


def test_validate_payload_rejects_too_long_step_detail() -> None:
    payload = _base_payload()
    payload["steps"][0]["detail"] = "x" * 2001
    errors = validate_payload(payload)
    assert any("steps[0].detail must be <= 2000 chars" in e for e in errors)


def test_validate_payload_accepts_step_detail_at_max_length() -> None:
    payload = _base_payload()
    payload["steps"][0]["detail"] = "x" * 2000
    assert validate_payload(payload) == []


def test_validate_payload_accepts_step_status_boundary_values() -> None:
    payload = _base_payload()
    payload["steps"][0]["status"] = 0
    payload["steps"][1]["status"] = 599
    assert validate_payload(payload) == []


def test_validate_payload_rejects_missing_required_fields() -> None:
    payload = _base_payload()
    del payload["schema_version"]
    del payload["generated_at_ms"]
    errors = validate_payload(payload)
    assert any("schema_version must be 1" in e for e in errors)
    assert any("generated_at_ms must be int" in e for e in errors)


def test_validate_payload_rejects_bool_numeric_top_level_fields() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = True
    payload["total_steps"] = True
    payload["ok_steps"] = True
    payload["err_steps"] = True
    errors = validate_payload(payload)
    assert any("generated_at_ms must be int" in e for e in errors)
    assert any("total_steps must be int" in e for e in errors)
    assert any("ok_steps must be int" in e for e in errors)
    assert any("err_steps must be int" in e for e in errors)


def test_validate_payload_rejects_non_positive_schema_version() -> None:
    payload = _base_payload()
    payload["schema_version"] = 0
    errors = validate_payload(payload)
    assert any("schema_version must be > 0" in e for e in errors)


def test_validate_payload_accepts_custom_expected_schema_version() -> None:
    payload = _base_payload()
    payload["schema_version"] = 2
    assert validate_payload(payload, expected_schema_version=2) == []


def test_validate_payload_rejects_non_positive_expected_schema_version_in_function() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_schema_version=0)
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_rejects_non_numeric_expected_schema_version_in_function() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_schema_version="abc")  # type: ignore[arg-type]
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_accepts_numeric_string_expected_schema_version_in_function() -> None:
    payload = _base_payload()
    assert validate_payload(payload, expected_schema_version="1") == []  # type: ignore[arg-type]


def test_validate_payload_rejects_float_string_expected_schema_version_in_function() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_schema_version="1.0")  # type: ignore[arg-type]
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_rejects_bool_expected_schema_version_in_function() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_schema_version=True)  # type: ignore[arg-type]
    assert any("expected_schema_version must be a positive integer" in e for e in errors)


def test_validate_payload_rejects_ok_true_with_failed_step() -> None:
    payload = _base_payload()
    payload["failed_step"] = "b"
    payload["steps"][1]["ok"] = False
    payload["ok_steps"] = 1
    payload["err_steps"] = 1
    errors = validate_payload(payload)
    assert any("failed_step must be empty when ok == true" in e for e in errors)


def test_validate_payload_rejects_ok_false_without_failed_step() -> None:
    payload = _base_payload()
    payload["ok"] = False
    payload["failed_step"] = ""
    payload["err_steps"] = 1
    payload["ok_steps"] = 1
    payload["steps"][1]["ok"] = False
    errors = validate_payload(payload)
    assert any("failed_step must be non-empty when ok == false" in e for e in errors)


def test_validate_payload_rejects_ok_true_with_nonzero_err_steps() -> None:
    payload = _base_payload()
    payload["err_steps"] = 1
    payload["ok_steps"] = 1
    errors = validate_payload(payload)
    assert any("err_steps must be 0 when ok == true" in e for e in errors)


def test_validate_payload_rejects_ok_true_with_ok_steps_not_equal_total() -> None:
    payload = _base_payload()
    payload["ok_steps"] = 1
    payload["err_steps"] = 0
    payload["steps"][1]["ok"] = True
    errors = validate_payload(payload)
    assert any("ok_steps must equal total_steps when ok == true" in e for e in errors)


def test_validate_payload_rejects_ok_false_with_zero_err_steps() -> None:
    payload = _base_payload()
    payload["ok"] = False
    payload["failed_step"] = "b"
    payload["ok_steps"] = 2
    payload["err_steps"] = 0
    payload["steps"][1]["ok"] = False
    errors = validate_payload(payload)
    assert any("err_steps must be >= 1 when ok == false" in e for e in errors)


def test_validate_payload_rejects_failed_step_not_in_steps() -> None:
    payload = _base_payload()
    payload["steps"][1]["ok"] = False
    payload["ok"] = False
    payload["ok_steps"] = 1
    payload["err_steps"] = 1
    payload["failed_step"] = "not-exists"
    errors = validate_payload(payload)
    assert any("failed_step must match one of steps[].name" in e for e in errors)


def test_validate_payload_rejects_failed_step_not_marked_failed() -> None:
    payload = _base_payload()
    payload["ok"] = False
    payload["failed_step"] = "a"
    payload["steps"][1]["ok"] = False
    payload["ok_steps"] = 1
    payload["err_steps"] = 1
    errors = validate_payload(payload)
    assert any("failed_step must reference a step with ok == false" in e for e in errors)


def test_validate_payload_rejects_failed_step_not_last_step() -> None:
    payload = _base_payload()
    payload["ok"] = False
    payload["failed_step"] = "a"
    payload["steps"][0]["ok"] = False
    payload["steps"][1]["ok"] = False
    payload["ok_steps"] = 0
    payload["err_steps"] = 2
    errors = validate_payload(payload)
    assert any("failed_step must equal the last step name" in e for e in errors)


def test_validate_payload_rejects_non_monotonic_step_ts() -> None:
    payload = _base_payload()
    payload["steps"][0]["ts_ms"] = 1710000000005
    payload["steps"][1]["ts_ms"] = 1710000000002
    errors = validate_payload(payload)
    assert any("steps[].ts_ms must be non-decreasing" in e for e in errors)


def test_validate_payload_rejects_generated_at_earlier_than_last_step() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = 1710000000001
    errors = validate_payload(payload)
    assert any("generated_at_ms must be >= last step ts_ms" in e for e in errors)


def test_validate_payload_accepts_generated_at_equal_last_step_ts() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = payload["steps"][-1]["ts_ms"]
    assert validate_payload(payload) == []


def test_validator_cli_returns_2_when_input_missing(tmp_path: Path) -> None:
    missing = tmp_path / "not-found.json"
    result = _run_result_cli(missing)
    assert result.returncode == 2
    assert "result file not found" in result.stdout


def test_validator_cli_returns_0_when_contract_valid(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_base_payload(), ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(valid)
    assert result.returncode == 0
    assert "contract validation passed" in result.stdout


def test_validator_cli_returns_2_when_json_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    result = _run_result_cli(bad)
    assert result.returncode == 2
    assert "failed to parse JSON" in result.stdout


def test_validator_cli_returns_1_when_contract_invalid(tmp_path: Path) -> None:
    bad_contract = tmp_path / "bad-contract.json"
    bad_contract.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_ms": 1710000000000,
                "ok": True,
                "failed_step": "",
                "total_steps": 2,
                "ok_steps": 2,  # mismatch: steps only has one ok
                "err_steps": 0,
                "steps": [
                    {"name": "only", "status": 200, "ok": True, "detail": "", "ts_ms": 1710000000001}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = _run_result_cli(bad_contract)
    assert result.returncode == 1
    assert "contract validation failed" in result.stdout
    assert "ok_steps must equal count(step.ok == true)" in result.stdout


def test_validator_cli_accepts_expected_schema_version_override(tmp_path: Path) -> None:
    valid = tmp_path / "valid-v2.json"
    payload = _base_payload()
    payload["schema_version"] = 2
    valid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(valid, "--expected-schema-version", "2")
    assert result.returncode == 0
    assert "contract validation passed" in result.stdout


def test_validator_cli_rejects_when_expected_schema_version_mismatch(tmp_path: Path) -> None:
    valid = tmp_path / "valid-v2.json"
    payload = _base_payload()
    payload["schema_version"] = 2
    valid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(valid, "--expected-schema-version", "1")
    assert result.returncode == 1
    assert "schema_version must be 1" in result.stdout


def test_validator_cli_rejects_non_positive_schema_version(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-schema-version.json"
    payload = _base_payload()
    payload["schema_version"] = 0
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(invalid)
    assert result.returncode == 1
    assert "schema_version must be > 0" in result.stdout


def test_validator_cli_rejects_non_positive_expected_schema_version(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_base_payload(), ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(valid, "--expected-schema-version", "0")
    assert result.returncode == 2
    assert "expected-schema-version must be a positive integer" in result.stdout


def test_validator_cli_rejects_negative_expected_schema_version(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_base_payload(), ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(valid, "--expected-schema-version", "-1")
    assert result.returncode == 2
    assert "expected-schema-version must be a positive integer" in result.stdout


def test_validator_cli_returns_2_when_root_is_not_object(tmp_path: Path) -> None:
    arr_root = tmp_path / "array-root.json"
    arr_root.write_text(json.dumps([1, 2, 3], ensure_ascii=False), encoding="utf-8")
    result = _run_result_cli(arr_root)
    assert result.returncode == 2
    assert "root JSON value must be object" in result.stdout
