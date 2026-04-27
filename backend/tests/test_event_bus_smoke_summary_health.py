from __future__ import annotations

from scripts.event_bus_smoke_summary_health import classify_health


def test_classify_health_green_when_all_checks_ok() -> None:
    health, reason = classify_health(
        preflight_check="ok",
        preflight_reason="preflight_passed",
        contract_check="ok",
        contract_reason_code="schema_match+generated_at_valid",
    )
    assert health == "green"
    assert reason == "all_checks_ok"


def test_classify_health_yellow_when_contract_mismatch_only() -> None:
    health, reason = classify_health(
        preflight_check="ok",
        preflight_reason="preflight_passed",
        contract_check="mismatch",
        contract_reason_code="schema_version_mismatch",
    )
    assert health == "yellow"
    assert reason == "contract:schema_version_mismatch"


def test_classify_health_red_when_preflight_mismatch_only() -> None:
    health, reason = classify_health(
        preflight_check="mismatch",
        preflight_reason="missing_required_files",
        contract_check="ok",
        contract_reason_code="schema_match+generated_at_valid",
    )
    assert health == "red"
    assert reason == "preflight:missing_required_files"


def test_classify_health_red_when_both_mismatch() -> None:
    health, reason = classify_health(
        preflight_check="mismatch",
        preflight_reason="invalid_required_file_contract",
        contract_check="mismatch",
        contract_reason_code="invalid_generated_at_ms",
    )
    assert health == "red"
    assert reason == "preflight:invalid_required_file_contract,contract:invalid_generated_at_ms"


def test_classify_health_yellow_when_registry_degraded_only() -> None:
    health, reason = classify_health(
        preflight_check="ok",
        preflight_reason="preflight_passed",
        contract_check="ok",
        contract_reason_code="schema_match+generated_at_valid",
        preflight_reason_known=False,
        contract_reason_code_known=True,
    )
    assert health == "yellow"
    assert reason == "registry:unknown_reason_code_detected"


def test_classify_health_red_includes_registry_reason_when_preflight_failed() -> None:
    health, reason = classify_health(
        preflight_check="mismatch",
        preflight_reason="unknown_new_reason",
        contract_check="ok",
        contract_reason_code="schema_match+generated_at_valid",
        preflight_reason_known=False,
        contract_reason_code_known=True,
    )
    assert health == "red"
    assert reason == "preflight:unknown_new_reason,registry:unknown_reason_code_detected"
