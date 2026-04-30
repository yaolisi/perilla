from __future__ import annotations

import json

from scripts import validate_roadmap_acceptance_result as validator
from scripts.validate_roadmap_acceptance_result import validate_payload


def test_validate_payload_accepts_success_shape() -> None:
    payload = {
        "schema_version": 1,
        "generated_at_ms": 1700000000000,
        "ok": True,
        "phase_gate_score": 0.9,
        "phase_readiness_avg": 0.85,
        "phase_readiness_lowest": "phase2_advanced",
        "north_star_score": 0.92,
        "latest_go_no_go": "go",
        "release_gate": {
            "require_go": True,
            "min_readiness_avg": 0.8,
            "max_lowest_readiness_score": 0.7,
        },
    }
    assert validate_payload(payload) == []


def test_validate_payload_rejects_missing_error_for_failure() -> None:
    payload = {
        "schema_version": 1,
        "generated_at_ms": 1700000000000,
        "ok": False,
        "release_gate": {
            "require_go": False,
            "min_readiness_avg": None,
            "max_lowest_readiness_score": None,
        },
    }
    errors = validate_payload(payload)
    assert any("error must be non-empty string when ok==false" in err for err in errors)


def test_validator_main_returns_2_for_invalid_expected_schema_version(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    payload_path = tmp_path / "result.json"
    payload_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        validator.sys,
        "argv",
        [
            "validate_roadmap_acceptance_result.py",
            "--input",
            str(payload_path),
            "--expected-schema-version",
            "0",
        ],
    )
    assert validator.main() == 2


def test_validator_main_returns_1_for_contract_failure(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    payload_path = tmp_path / "result.json"
    payload_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setattr(
        validator.sys,
        "argv",
        [
            "validate_roadmap_acceptance_result.py",
            "--input",
            str(payload_path),
            "--expected-schema-version",
            "1",
        ],
    )
    assert validator.main() == 1
