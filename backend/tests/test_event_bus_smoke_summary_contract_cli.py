from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.event_bus_smoke_error_codes import ERR_PAYLOAD_SHA256_MISMATCH
from scripts.event_bus_smoke_summary_keys import (
    KEY_HEALTH,
    KEY_HEALTH_REASON_CODES,
    KEY_SUMMARY_SCHEMA_VERSION,
)
from tests._event_bus_smoke_summary_fixtures import base_summary_payload

def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run_validator(input_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(input_path),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def test_validator_cli_returns_0_when_contract_valid(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary.json"
    _write_json(valid, base_summary_payload())
    result = _run_validator(valid)
    assert result.returncode == 0
    assert "summary contract validation passed" in result.stdout


def test_validator_cli_returns_1_when_contract_invalid(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-summary.json"
    payload = base_summary_payload()
    payload[KEY_HEALTH_REASON_CODES] = []
    _write_json(invalid, payload)
    result = _run_validator(invalid)
    assert result.returncode == 1
    assert "summary contract validation failed" in result.stdout


def test_validator_cli_returns_2_when_input_missing(tmp_path: Path) -> None:
    missing = tmp_path / "not-found-summary.json"
    result = _run_validator(missing)
    assert result.returncode == 2
    assert "summary file not found" in result.stdout


def test_validator_cli_accepts_compatible_schema_mode(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary-v1.json"
    payload = base_summary_payload()
    payload[KEY_SUMMARY_SCHEMA_VERSION] = 1
    _write_json(valid, payload)
    result = _run_validator(
        valid,
        "--expected-summary-schema-version",
        "2",
        "--schema-mode",
        "compatible",
    )
    assert result.returncode == 0


def test_validator_cli_accepts_payload_sha256_mode_off(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary-off.json"
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "yellow"
    _write_json(valid, payload)
    result = _run_validator(valid, "--payload-sha256-mode", "off")
    assert result.returncode == 0


def test_validator_cli_rejects_payload_sha256_mismatch_in_strict_mode(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-summary-strict-sha.json"
    payload = base_summary_payload()
    payload[KEY_HEALTH] = "yellow"
    _write_json(invalid, payload)
    result = _run_validator(invalid, "--payload-sha256-mode", "strict")
    assert result.returncode == 1
    assert "payload_sha256 mismatch" in result.stdout
    assert f"[{ERR_PAYLOAD_SHA256_MISMATCH}]" in result.stdout


def test_validator_cli_rejects_non_positive_expected_schema_version_arg(tmp_path: Path) -> None:
    valid = tmp_path / "valid-summary-schema-arg.json"
    _write_json(valid, base_summary_payload())
    result = _run_validator(valid, "--expected-summary-schema-version", "0")
    assert result.returncode == 2
    assert "expected-summary-schema-version must be a positive integer" in result.stdout


def test_validator_cli_returns_2_when_json_is_not_object(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-root.json"
    _write_json(invalid, ["not-an-object"])
    result = _run_validator(invalid)
    assert result.returncode == 2
    assert "root JSON value must be object" in result.stdout


def test_validator_cli_returns_2_when_json_parse_fails(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-json.txt"
    invalid.write_text("{oops", encoding="utf-8")
    result = _run_validator(invalid)
    assert result.returncode == 2
    assert "failed to parse JSON" in result.stdout
