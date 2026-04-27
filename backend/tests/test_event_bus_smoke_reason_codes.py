from __future__ import annotations

from scripts.event_bus_smoke_reason_codes import (
    ALLOWED_CONTRACT_REASON_CODES,
    ALLOWED_PREFLIGHT_REASON_CODES,
    CONTRACT_REASON_SCHEMA_MATCH,
    CONTRACT_REASON_UNKNOWN,
    PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT,
    PREFLIGHT_REASON_MISSING_PREFLIGHT_LOG,
    PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES,
    PREFLIGHT_REASON_MISSING_REQUIRED_FILES,
    PREFLIGHT_REASON_PREFLIGHT_ERROR,
    PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION,
    REASON_REGISTRY_CONFIG,
    SNIPPET_INVALID_REQUIRED_FILE_CONTRACT,
    SNIPPET_MISSING_PYTHON_PACKAGES,
    SNIPPET_MISSING_REQUIRED_FILES,
    SNIPPET_UNSUPPORTED_PYTHON_VERSION,
    build_contract_reason_code,
    find_unknown_contract_reason_codes,
    is_known_preflight_reason_code,
    map_preflight_error_to_reason,
    preflight_machine_error_lines,
    smoke_dlq_log_error_lines,
)


def test_map_preflight_error_to_reason_known_patterns() -> None:
    assert map_preflight_error_to_reason("[ERR] Missing required files: a.txt") == PREFLIGHT_REASON_MISSING_REQUIRED_FILES
    assert (
        map_preflight_error_to_reason("[ERR] Invalid required file contract: pytest.smoke.ini")
        == PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT
    )
    assert map_preflight_error_to_reason("[ERR] Missing python packages: pytest") == PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES
    assert map_preflight_error_to_reason("[ERR] Python 3.10+ is required, got 3.9") == PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION


def test_map_preflight_error_to_reason_fallback() -> None:
    assert map_preflight_error_to_reason("[ERR] something else") == PREFLIGHT_REASON_PREFLIGHT_ERROR


def test_preflight_machine_error_lines_matches_github_summary_rule() -> None:
    log = """noise line
[preflight_missing_modules] Missing python packages: foo (details={})
"""
    lines = log.splitlines()
    err = preflight_machine_error_lines(lines)
    assert err == ["[preflight_missing_modules] Missing python packages: foo (details={})"]
    assert (
        map_preflight_error_to_reason(err[0].strip()) == PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES
    )


def test_preflight_machine_error_lines_ignores_whitespace_prefixed_codes() -> None:
    lines = ["  \t[preflight_missing_files] Missing required files: x.txt"]
    assert len(preflight_machine_error_lines(lines)) == 1


def test_smoke_dlq_log_error_lines_counts_legacy_err_and_smoke_dlq_codes() -> None:
    lines = [
        "[OK] step -> HTTP 200",
        "[ERR] event-bus/status -> HTTP 500",
        "[smoke_dlq_http_step] event-bus/status -> HTTP 500 (details={})",
        "[smoke_dlq_assertion_failed] assert dry-run assertion failed (details={})",
        "noise",
    ]
    err = smoke_dlq_log_error_lines(lines)
    assert len(err) == 3
    assert "[ERR]" in err[0]


def test_map_preflight_error_to_reason_accepts_code_prefixed_preflight_lines() -> None:
    """Locks mapping for current preflight stderr (e.g. GitHub Actions log parsing)."""
    assert (
        map_preflight_error_to_reason(
            "[preflight_missing_files] Missing required files: a.txt (details={\"missing_files\":[\"a.txt\"]})"
        )
        == PREFLIGHT_REASON_MISSING_REQUIRED_FILES
    )
    assert (
        map_preflight_error_to_reason(
            "[preflight_required_file_contract_invalid] Invalid required file contract: x (details={})"
        )
        == PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT
    )
    assert (
        map_preflight_error_to_reason(
            "[preflight_missing_modules] Missing python packages: pytest (details={})"
        )
        == PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES
    )
    assert (
        map_preflight_error_to_reason(
            "[preflight_python_version_unsupported] Python 3.10+ is required, got 3.9 (details={})"
        )
        == PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION
    )


def test_build_contract_reason_code_returns_ok_code_when_ok() -> None:
    assert build_contract_reason_code(["schema_version_mismatch"], contract_ok=True) == CONTRACT_REASON_SCHEMA_MATCH


def test_build_contract_reason_code_sorts_and_deduplicates() -> None:
    code = build_contract_reason_code(
        ["missing_generated_at_ms", "schema_version_mismatch", "missing_generated_at_ms"],
        contract_ok=False,
    )
    assert code == "missing_generated_at_ms,schema_version_mismatch"


def test_build_contract_reason_code_returns_unknown_when_empty() -> None:
    assert build_contract_reason_code([], contract_ok=False) == CONTRACT_REASON_UNKNOWN


def test_is_known_preflight_reason_code() -> None:
    assert is_known_preflight_reason_code(PREFLIGHT_REASON_MISSING_PREFLIGHT_LOG) is True
    assert is_known_preflight_reason_code("not_registered") is False


def test_find_unknown_contract_reason_codes() -> None:
    assert find_unknown_contract_reason_codes("missing_generated_at_ms,custom_error") == ["custom_error"]
    assert find_unknown_contract_reason_codes(CONTRACT_REASON_SCHEMA_MATCH) == []


def test_allowed_reason_code_sets_non_empty() -> None:
    assert len(ALLOWED_PREFLIGHT_REASON_CODES) >= 3
    assert len(ALLOWED_CONTRACT_REASON_CODES) >= 3


def test_reason_registry_config_contains_required_sections() -> None:
    assert "preflight_codes" in REASON_REGISTRY_CONFIG
    assert "contract_codes" in REASON_REGISTRY_CONFIG
    assert "preflight_error_mapping" in REASON_REGISTRY_CONFIG
    assert len(REASON_REGISTRY_CONFIG["preflight_error_mapping"]) >= 3


def test_preflight_error_mapping_order_is_stable_for_priority() -> None:
    mapping = list(REASON_REGISTRY_CONFIG["preflight_error_mapping"])
    snippets = [item[0] for item in mapping]
    assert snippets == [
        SNIPPET_MISSING_REQUIRED_FILES,
        SNIPPET_INVALID_REQUIRED_FILE_CONTRACT,
        SNIPPET_MISSING_PYTHON_PACKAGES,
        SNIPPET_UNSUPPORTED_PYTHON_VERSION,
    ]
