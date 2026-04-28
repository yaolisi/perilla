from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from scripts.event_bus_smoke_error_codes import (
    ERR_GH_TRIGGER_COMPLETED_AT_ORDER_INVALID,
    ERR_GH_TRIGGER_CONCLUSION_EXPECTED_MISMATCH,
    ERR_GH_TRIGGER_DECLARED_PATH_MISMATCH,
    ERR_GH_TRIGGER_DURATION_CALC_MISMATCH,
    ERR_GH_TRIGGER_EXPECTED_FIELD_MISMATCH,
    ERR_GH_TRIGGER_EXPECTED_CONCLUSION_INVALID,
    ERR_GH_TRIGGER_GENERATED_AT_POSITIVE_INVALID,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_INVALID,
    ERR_GH_TRIGGER_PAYLOAD_SHA256_MISMATCH,
    ERR_GH_TRIGGER_RUN_URL_RUN_ID_MISMATCH,
    ERR_GH_TRIGGER_SCHEMA_MODE_INVALID,
    ERR_GH_TRIGGER_SHA_MODE_MISMATCH,
    ERR_GH_TRIGGER_THRESHOLD_INVALID,
)
from scripts.event_bus_smoke_gh_constants import ALLOWED_GH_RUN_CONCLUSIONS_SET, GH_TRIGGER_AUDIT_SOURCE
from scripts.event_bus_smoke_gh_contract_keys import GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS
from scripts.validate_event_bus_smoke_gh_trigger_inputs_audit import validate_payload


def _with_payload_hash(payload: Dict[str, Any]) -> Dict[str, Any]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core["payload_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def _base_payload() -> Dict[str, Any]:
    return _with_payload_hash(
        {
            "schema_version": 1,
            "generated_at_ms": 1710000000000,
            "source": "event_bus_smoke_gh_trigger_watch.py",
            "workflow": "event-bus-dlq-smoke.yml",
            "mode": "strict",
            "base_url": "http://127.0.0.1:8000",
            "event_type": "agent.status.changed",
            "limit": "20",
            "expected_schema_version": "1",
            "expected_summary_schema_version": "1",
            "expected_conclusion": "success",
            "payload_sha256_mode": "strict",
            "result_file_stale_threshold_ms": "600000",
            "file_suffix": "run-1",
            "trigger_inputs_audit_file": ".tmp/gh-trigger-inputs.json",
            "run_id": "101",
            "run_url": "https://github.com/org/repo/actions/runs/101",
            "conclusion": "success",
            "completed_at_ms": 1710000001000,
            "duration_ms": 1000,
        }
    )


def test_validate_payload_accepts_valid_contract() -> None:
    assert validate_payload(_base_payload()) == []


def test_trigger_audit_contract_reuses_shared_constants() -> None:
    payload = _base_payload()
    assert payload["source"] == GH_TRIGGER_AUDIT_SOURCE
    assert payload["expected_conclusion"] in ALLOWED_GH_RUN_CONCLUSIONS_SET
    assert payload["conclusion"] in ALLOWED_GH_RUN_CONCLUSIONS_SET


def test_trigger_audit_expected_keys_match_base_payload() -> None:
    payload = _base_payload()
    assert set(payload.keys()) == set(GH_TRIGGER_INPUTS_AUDIT_EXPECTED_KEYS)


def test_validate_payload_rejects_sha256_mismatch() -> None:
    payload = _base_payload()
    payload["mode"] = "compatible"
    errors = validate_payload(payload)
    assert any("payload_sha256 mismatch" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_PAYLOAD_SHA256_MISMATCH}]" in e for e in errors)


def test_validate_payload_accepts_sha256_mismatch_when_mode_off() -> None:
    payload = _base_payload()
    payload["mode"] = "compatible"
    assert validate_payload(payload, payload_sha256_mode="off") == []


def test_validate_payload_rejects_invalid_sha256_mode() -> None:
    errors = validate_payload(_base_payload(), payload_sha256_mode="bad")
    assert any("payload_sha256_mode must be one of: strict,off" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_PAYLOAD_SHA256_MODE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_non_positive_generated_at_ms() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = 0
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("generated_at_ms must be > 0" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_GENERATED_AT_POSITIVE_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_bool_numeric_runtime_fields() -> None:
    payload = _base_payload()
    payload["schema_version"] = True
    payload["generated_at_ms"] = True
    payload["completed_at_ms"] = True
    payload["duration_ms"] = False
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("schema_version must be 1" in e for e in errors)
    assert any("generated_at_ms must be int" in e for e in errors)
    assert any("completed_at_ms must be int" in e for e in errors)
    assert any("duration_ms must be int" in e for e in errors)


def test_validate_payload_rejects_non_positive_completed_at_ms() -> None:
    payload = _base_payload()
    payload["completed_at_ms"] = 0
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("completed_at_ms must be > 0" in e for e in errors)


def test_validate_payload_rejects_negative_duration_ms() -> None:
    payload = _base_payload()
    payload["duration_ms"] = -1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("duration_ms must be >= 0" in e for e in errors)


def test_validate_payload_rejects_inconsistent_duration_ms() -> None:
    payload = _base_payload()
    payload["duration_ms"] = 999
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("duration_ms must equal completed_at_ms - generated_at_ms" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_DURATION_CALC_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_completed_before_generated() -> None:
    payload = _base_payload()
    payload["generated_at_ms"] = 1710000001000
    payload["completed_at_ms"] = 1710000000000
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("completed_at_ms must be >= generated_at_ms" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_COMPLETED_AT_ORDER_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_non_numeric_limit() -> None:
    payload = _base_payload()
    payload["limit"] = "abc"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("limit must be positive integer string" in e for e in errors)


def test_validate_payload_rejects_non_positive_expected_schema_version_field() -> None:
    payload = _base_payload()
    payload["expected_schema_version"] = "0"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("expected_schema_version must be positive integer string" in e for e in errors)


def test_validate_payload_rejects_negative_stale_threshold_field() -> None:
    payload = _base_payload()
    payload["result_file_stale_threshold_ms"] = "-1"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("result_file_stale_threshold_ms must be non-negative integer string" in e for e in errors)


def test_validate_payload_rejects_invalid_run_url() -> None:
    payload = _base_payload()
    payload["run_url"] = "not-a-url"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("run_url must be http(s) URL" in e for e in errors)


def test_validate_payload_rejects_invalid_base_url() -> None:
    payload = _base_payload()
    payload["base_url"] = "localhost:8000"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("base_url must be http(s) URL" in e for e in errors)


def test_validate_payload_rejects_invalid_source() -> None:
    payload = _base_payload()
    payload["source"] = "unknown_writer.py"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("source must be supported audit writer" in e for e in errors)


def test_validate_payload_rejects_invalid_workflow_filename() -> None:
    payload = _base_payload()
    payload["workflow"] = "backend/.github/workflows/event-bus-dlq-smoke.yml"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("workflow must be yml/yaml filename" in e for e in errors)


def test_validate_payload_accepts_empty_file_suffix() -> None:
    payload = _base_payload()
    payload["file_suffix"] = ""
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    assert validate_payload(payload) == []


def test_validate_payload_rejects_invalid_file_suffix_characters() -> None:
    payload = _base_payload()
    payload["file_suffix"] = "bad suffix"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("file_suffix is invalid" in e for e in errors)


def test_validate_payload_rejects_too_long_file_suffix() -> None:
    payload = _base_payload()
    payload["file_suffix"] = "a" * 65
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("file_suffix is invalid" in e for e in errors)


def test_validate_payload_rejects_invalid_conclusion() -> None:
    payload = _base_payload()
    payload["conclusion"] = "unknown"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("conclusion must be valid GitHub run conclusion" in e for e in errors)


def test_validate_payload_rejects_conclusion_mismatch_with_expected_conclusion() -> None:
    payload = _base_payload()
    payload["expected_conclusion"] = "failure"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("conclusion must equal expected_conclusion" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_CONCLUSION_EXPECTED_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_non_numeric_run_id() -> None:
    payload = _base_payload()
    payload["run_id"] = "run-101"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("run_id must be positive integer string" in e for e in errors)


def test_validate_payload_rejects_run_url_without_run_id() -> None:
    payload = _base_payload()
    payload["run_url"] = "https://github.com/org/repo/actions/runs/999"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("run_url must match .../actions/runs/{run_id}" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_RUN_URL_RUN_ID_MISMATCH}]" in e for e in errors)


def test_validate_payload_rejects_run_url_tail_partial_match() -> None:
    payload = _base_payload()
    payload["run_id"] = "101"
    payload["run_url"] = "https://github.com/org/repo/actions/runs/1101"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload)
    assert any("run_url must match .../actions/runs/{run_id}" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_RUN_URL_RUN_ID_MISMATCH}]" in e for e in errors)


def test_validate_payload_accepts_older_schema_in_compatible_mode() -> None:
    payload = _base_payload()
    payload["schema_version"] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    assert validate_payload(payload, expected_schema_version=2, schema_mode="compatible") == []


def test_validate_payload_rejects_older_schema_in_strict_mode() -> None:
    payload = _base_payload()
    payload["schema_version"] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload, expected_schema_version=2, schema_mode="strict")
    assert any("schema_version must be 2" in e for e in errors)


def test_validate_payload_rejects_invalid_schema_mode() -> None:
    errors = validate_payload(_base_payload(), schema_mode="bad")
    assert any("schema_mode must be one of: strict,compatible" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_SCHEMA_MODE_INVALID}]" in e for e in errors)


def test_make_validate_gh_trigger_inputs_audit_passes(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_PAYLOAD_SHA256_MODE=strict",
            "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_VERSION=1",
            "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE=strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "validation passed" in (result.stdout + result.stderr)


def test_make_validate_gh_trigger_inputs_audit_rejects_empty_file_var() -> None:
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE=",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE must be non-empty" in (result.stdout + result.stderr)


def test_make_validate_gh_trigger_inputs_audit_rejects_invalid_schema_mode(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE=invalid",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_SCHEMA_MODE must be one of: strict,compatible" in (
        result.stdout + result.stderr
    )


def test_make_validate_gh_trigger_inputs_audit_rejects_invalid_max_duration(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS=-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_DURATION_MS must be empty or a non-negative integer" in (
        result.stdout + result.stderr
    )


def test_validator_cli_returns_0_for_valid_payload(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "validation passed" in result.stdout


def test_validator_cli_accepts_compatible_schema_mode(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit-v1.json"
    payload = _base_payload()
    payload["schema_version"] = 1
    payload["trigger_inputs_audit_file"] = str(path)
    path.write_text(
        json.dumps(_with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"}), ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-schema-version",
            "2",
            "--schema-mode",
            "compatible",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_validate_payload_rejects_trigger_mode_mismatch() -> None:
    payload = _base_payload()
    payload["mode"] = "compatible"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload, expected_trigger_mode="strict")
    assert any("mode in payload must match --expected-trigger-mode" in e for e in errors)


def test_validator_cli_rejects_trigger_mode_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload["mode"] = "compatible"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-trigger-mode",
            "strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "mode in payload must match --expected-trigger-mode" in result.stdout


def test_validate_payload_rejects_expected_workflow_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_workflow="other-workflow.yml")
    assert any("workflow in payload must match --expected-workflow" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_EXPECTED_FIELD_MISMATCH}]" in e for e in errors)


def test_validator_cli_rejects_expected_workflow_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-workflow",
            "other-workflow.yml",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "workflow in payload must match --expected-workflow" in result.stdout


def test_validate_payload_rejects_expected_base_url_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_base_url="http://127.0.0.1:9999")
    assert any("base_url in payload must match --expected-base-url" in e for e in errors)


def test_validate_payload_rejects_expected_event_type_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_event_type="agent.other.changed")
    assert any("event_type in payload must match --expected-event-type" in e for e in errors)


def test_validate_payload_rejects_expected_limit_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_limit="99")
    assert any("limit in payload must match --expected-limit" in e for e in errors)


def test_validate_payload_rejects_expected_stale_threshold_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_result_file_stale_threshold_ms="1")
    assert any("result_file_stale_threshold_ms in payload must match --expected-result-file-stale-threshold-ms" in e for e in errors)


def test_validate_payload_rejects_expected_summary_schema_version_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_summary_schema_version="2")
    assert any("expected_summary_schema_version in payload must match --expected-summary-schema-version" in e for e in errors)


def test_validate_payload_rejects_expected_result_schema_version_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_result_schema_version="2")
    assert any("expected_schema_version in payload must match --expected-result-schema-version" in e for e in errors)


def test_validate_payload_rejects_expected_file_suffix_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_file_suffix="run-2")
    assert any("file_suffix in payload must match --expected-file-suffix" in e for e in errors)


def test_validate_payload_rejects_expected_conclusion_mismatch() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, expected_conclusion="failure")
    assert any("conclusion in payload must match --expected-conclusion" in e for e in errors)


def test_validate_payload_rejects_invalid_expected_conclusion_value() -> None:
    errors = validate_payload(_base_payload(), expected_conclusion="unknown")
    assert any("expected_conclusion must be one of supported GitHub run conclusions" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_EXPECTED_CONCLUSION_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_duration_exceeding_max() -> None:
    payload = _base_payload()
    errors = validate_payload(payload, max_duration_ms=500)
    assert any("duration_ms in payload must be <= --max-duration-ms" in e for e in errors)


def test_validate_payload_rejects_negative_max_duration() -> None:
    errors = validate_payload(_base_payload(), max_duration_ms=-1)
    assert any("max_duration_ms must be a non-negative integer" in e for e in errors)
    assert any(f"[{ERR_GH_TRIGGER_THRESHOLD_INVALID}]" in e for e in errors)


def test_validate_payload_rejects_audit_older_than_max_age() -> None:
    payload = _base_payload()
    payload["completed_at_ms"] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    errors = validate_payload(payload, max_age_ms=10)
    assert any("audit age must be <= --max-age-ms" in e for e in errors)


def test_validate_payload_rejects_negative_max_age() -> None:
    errors = validate_payload(_base_payload(), max_age_ms=-1)
    assert any("max_age_ms must be a non-negative integer" in e for e in errors)


def test_validator_cli_rejects_expected_base_url_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-base-url",
            "http://127.0.0.1:9999",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "base_url in payload must match --expected-base-url" in result.stdout


def test_validator_cli_rejects_expected_limit_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-limit",
            "99",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "limit in payload must match --expected-limit" in result.stdout


def test_validator_cli_rejects_expected_result_schema_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-result-schema-version",
            "2",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "expected_schema_version in payload must match --expected-result-schema-version" in result.stdout


def test_validator_cli_rejects_expected_file_suffix_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-file-suffix",
            "run-2",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "file_suffix in payload must match --expected-file-suffix" in result.stdout


def test_validator_cli_rejects_expected_conclusion_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-conclusion",
            "failure",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "conclusion in payload must match --expected-conclusion" in result.stdout


def test_validator_cli_rejects_invalid_expected_conclusion_value(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--expected-conclusion",
            "unknown",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "expected_conclusion must be one of supported GitHub run conclusions" in result.stdout


def test_validator_cli_rejects_duration_exceeding_max(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--max-duration-ms",
            "500",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "duration_ms in payload must be <= --max-duration-ms" in result.stdout


def test_validator_cli_rejects_audit_older_than_max_age(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload["completed_at_ms"] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--max-age-ms",
            "10",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "audit age must be <= --max-age-ms" in result.stdout


def test_make_validate_gh_trigger_inputs_audit_rejects_invalid_max_age(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=-1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS must be empty or a non-negative integer" in (
        result.stdout + result.stderr
    )


def test_make_validate_gh_trigger_inputs_audit_rejects_aged_payload_by_max_age(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload["completed_at_ms"] = 1
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            "make",
            "event-bus-smoke-validate-gh-trigger-inputs-audit",
            f"EVENT_BUS_SMOKE_GH_TRIGGER_INPUTS_AUDIT_FILE={path}",
            "EVENT_BUS_SMOKE_GH_TRIGGER_MAX_AGE_MS=10",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "audit age must be <= --max-age-ms" in (result.stdout + result.stderr)


def test_validator_cli_rejects_declared_path_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(tmp_path / "other.json")
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "trigger_inputs_audit_file must match --input path" in result.stdout
    assert f"[{ERR_GH_TRIGGER_DECLARED_PATH_MISMATCH}]" in result.stdout


def test_validator_cli_rejects_payload_sha_mode_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(path)
    payload["payload_sha256_mode"] = "off"
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
            "--payload-sha256-mode",
            "strict",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "payload_sha256_mode in payload must match --payload-sha256-mode" in result.stdout
    assert f"[{ERR_GH_TRIGGER_SHA_MODE_MISMATCH}]" in result.stdout


def test_validator_cli_accepts_path_match_after_normalization(tmp_path: Path) -> None:
    path = tmp_path / "dir" / "trigger-inputs-audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    declared_equivalent = path.parent / ".." / "dir" / "trigger-inputs-audit.json"
    payload = _base_payload()
    payload["trigger_inputs_audit_file"] = str(declared_equivalent)
    payload = _with_payload_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
