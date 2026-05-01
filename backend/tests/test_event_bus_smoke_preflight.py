from __future__ import annotations

import re
import json
from pathlib import Path

import pytest

from scripts.event_bus_smoke_error_code_guard_targets import (
    ERROR_CODE_GUARD_TEST_GLOB,
    ERROR_CODE_GUARD_TEST_PATH_PREFIX,
    error_code_guard_test_regex,
    error_code_guard_test_path_regex,
)
import scripts.event_bus_smoke_preflight as preflight_module
from tests.repo_paths import repo_path, repo_run_python
from scripts.event_bus_smoke_error_code_guard_targets import ERROR_CODE_GUARD_TEST_FILES
from scripts.event_bus_smoke_preflight import (
    DEFAULT_REQUIRED_FILES,
    MAKEFILE_PATH,
    PREFLIGHT_JSON_SCHEMA_VERSION,
    SMOKE_PYTEST_INI_PATH,
    monorepo_requires_makefile_in_preflight,
    _normalize_newlines,
    _validate_makefile_error_code_guard_blocks,
    _validate_pytest_smoke_ini,
    _unique,
    _is_python_version_supported,
    run_preflight,
)

ERROR_CODE_GUARD_TEST_REGEX = error_code_guard_test_regex()
ERROR_CODE_GUARD_TEST_PATH_REGEX = error_code_guard_test_path_regex()
CORE_GOVERNANCE_TEST_FILES = (
    "backend/tests/test_event_bus_smoke_preflight.py",
    "backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
    "backend/tests/test_event_bus_smoke_json_integrity_contract.py",
)


def _extract_details_json(line: str) -> dict[str, object]:
    match = re.search(r"\(details=(\{.*\})\)$", line.strip())
    assert match is not None
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    return payload


def test_run_preflight_passes_when_dependencies_exist() -> None:
    rc = run_preflight(
        required_modules=["pytest"],
        required_files=["backend/tests/pytest.smoke.ini"],
    )
    assert rc == 0


def test_run_preflight_fails_on_missing_module() -> None:
    rc = run_preflight(
        required_modules=["definitely_missing_module_for_preflight_test"],
        required_files=[],
    )
    assert rc == 2


def test_run_preflight_missing_module_output_is_code_prefixed(capsys) -> None:
    rc = run_preflight(
        required_modules=["definitely_missing_module_for_preflight_prefix_test"],
        required_files=[],
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out.strip().startswith("[preflight_missing_modules] ")
    assert "(details=" in captured.out


def test_run_preflight_deduplicates_missing_modules_in_output(capsys) -> None:
    rc = run_preflight(
        required_modules=[
            "definitely_missing_module_for_preflight_test_dup",
            "definitely_missing_module_for_preflight_test_dup",
        ],
        required_files=[],
    )
    captured = capsys.readouterr()
    assert rc == 2
    details = _extract_details_json(captured.out)
    assert details["missing_count"] == 1
    assert details["missing_modules"] == ["definitely_missing_module_for_preflight_test_dup"]


def test_run_preflight_success_reports_deduplicated_counts(capsys) -> None:
    rc = run_preflight(
        required_modules=["pytest", "pytest"],
        required_files=["backend/tests/pytest.smoke.ini", "backend/tests/pytest.smoke.ini"],
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "required_modules=1" in captured.out
    assert "required_files=1" in captured.out


def test_run_preflight_fails_on_missing_file() -> None:
    rc = run_preflight(
        required_modules=[],
        required_files=["backend/tests/__definitely_missing_file__.txt"],
    )
    assert rc == 2


def test_run_preflight_missing_file_output_is_code_prefixed(capsys) -> None:
    rc = run_preflight(
        required_modules=[],
        required_files=["backend/tests/__definitely_missing_file_prefix_test__.txt"],
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out.strip().startswith("[preflight_missing_files] ")
    assert "(details=" in captured.out


def test_default_required_files_include_preflight_script() -> None:
    assert "backend/scripts/event_bus_smoke_preflight.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_validator() -> None:
    assert "backend/scripts/validate_event_bus_smoke_result.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_summary_contract_validator() -> None:
    assert "backend/scripts/validate_event_bus_smoke_summary_result.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_error_codes_module() -> None:
    assert "backend/scripts/event_bus_smoke_error_codes.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_error_code_guard_targets_module() -> None:
    assert "backend/scripts/event_bus_smoke_error_code_guard_targets.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_json_integrity_module() -> None:
    assert "backend/scripts/event_bus_smoke_json_integrity.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_makefile_utils_module() -> None:
    assert "backend/scripts/event_bus_smoke_makefile_utils.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_makefile_path() -> None:
    if monorepo_requires_makefile_in_preflight():
        assert MAKEFILE_PATH in DEFAULT_REQUIRED_FILES
    else:
        assert MAKEFILE_PATH not in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_error_code_contract_test() -> None:
    assert "backend/tests/test_event_bus_smoke_error_code_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_error_codes_constants_contract_test() -> None:
    assert "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_error_code_coverage_contract_test() -> None:
    assert "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_each_error_code_guard_test_once() -> None:
    for test_path in ERROR_CODE_GUARD_TEST_FILES:
        assert test_path in DEFAULT_REQUIRED_FILES
        assert DEFAULT_REQUIRED_FILES.count(test_path) == 1


def test_default_required_files_error_code_tests_match_shared_guard_list_exactly() -> None:
    extracted = {
        path
        for path in DEFAULT_REQUIRED_FILES
        if re.fullmatch(ERROR_CODE_GUARD_TEST_PATH_REGEX, path)
    }
    assert extracted == set(ERROR_CODE_GUARD_TEST_FILES)


def test_default_required_files_error_code_tests_follow_shared_order() -> None:
    positions = [DEFAULT_REQUIRED_FILES.index(path) for path in ERROR_CODE_GUARD_TEST_FILES]
    assert positions == sorted(positions)


def test_default_required_files_error_code_tests_are_contiguous_block() -> None:
    positions = [DEFAULT_REQUIRED_FILES.index(path) for path in ERROR_CODE_GUARD_TEST_FILES]
    start = min(positions)
    expected = list(range(start, start + len(ERROR_CODE_GUARD_TEST_FILES)))
    assert positions == expected


def test_default_required_files_error_code_tests_match_shared_order_exactly() -> None:
    extracted = tuple(
        path
        for path in DEFAULT_REQUIRED_FILES
        if re.fullmatch(ERROR_CODE_GUARD_TEST_PATH_REGEX, path)
    )
    assert extracted == ERROR_CODE_GUARD_TEST_FILES


def test_error_code_guard_test_path_prefix_contract() -> None:
    assert ERROR_CODE_GUARD_TEST_PATH_PREFIX == "backend/tests/"


def test_default_required_files_include_gh_trigger_watch_script() -> None:
    assert "backend/scripts/event_bus_smoke_gh_trigger_watch.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_summary_keys_module() -> None:
    assert "backend/scripts/event_bus_smoke_summary_keys.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_summary_payload_module() -> None:
    assert "backend/scripts/event_bus_smoke_summary_payload.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_summary_reason_codes_module() -> None:
    assert "backend/scripts/event_bus_smoke_summary_reason_codes.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_inputs_snapshot_validator() -> None:
    assert "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_inputs_audit_validator() -> None:
    assert "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_constants_module() -> None:
    assert "backend/scripts/event_bus_smoke_gh_constants.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_audit_payload_module() -> None:
    assert "backend/scripts/event_bus_smoke_gh_trigger_audit_payload.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_guard_summary_module() -> None:
    assert "backend/scripts/event_bus_smoke_contract_guard_summary.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_guard_status_printer_module() -> None:
    assert "backend/scripts/print_event_bus_smoke_contract_guard_status.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_audit_mapping_module() -> None:
    assert "backend/scripts/event_bus_smoke_gh_trigger_audit_arg_map.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_max_age_make_validation_test() -> None:
    assert "backend/tests/test_make_event_bus_smoke_gh_trigger_max_age_validation.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_workflow_contract_guard_step_test() -> None:
    assert "backend/tests/test_event_bus_smoke_workflow_contract_guard_step.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_expected_conclusion_make_validation_test() -> None:
    assert "backend/tests/test_make_event_bus_smoke_gh_trigger_expected_conclusion_validation.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_guard_make_test() -> None:
    assert "backend/tests/test_make_event_bus_smoke_contract_guard.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_guard_summary_test() -> None:
    assert "backend/tests/test_event_bus_smoke_contract_guard_summary.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_contract_guard_status_json_test() -> None:
    assert "backend/tests/test_make_event_bus_smoke_contract_guard_status_json.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_audit_mapping_contract_test() -> None:
    assert "backend/tests/test_make_event_bus_smoke_gh_trigger_audit_mapping_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_gh_trigger_audit_payload_contract_test() -> None:
    assert "backend/tests/test_event_bus_smoke_gh_trigger_audit_payload_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_smoke_pytest_config() -> None:
    assert SMOKE_PYTEST_INI_PATH in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_json_integrity_contract_test() -> None:
    assert "backend/tests/test_event_bus_smoke_json_integrity_contract.py" in DEFAULT_REQUIRED_FILES


def test_default_required_files_include_core_governance_tests_once_and_ordered() -> None:
    positions = []
    for path in CORE_GOVERNANCE_TEST_FILES:
        assert path in DEFAULT_REQUIRED_FILES
        assert DEFAULT_REQUIRED_FILES.count(path) == 1
        positions.append(DEFAULT_REQUIRED_FILES.index(path))
    assert positions == sorted(positions)


def test_validate_pytest_smoke_ini_accepts_expected_content(tmp_path) -> None:
    cfg = tmp_path / "pytest.smoke.ini"
    cfg.write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    assert _validate_pytest_smoke_ini(str(cfg)) == []


def test_validate_pytest_smoke_ini_rejects_missing_pytest_section(tmp_path) -> None:
    cfg = tmp_path / "pytest.smoke.ini"
    cfg.write_text("addopts = -q\n", encoding="utf-8")
    errors = _validate_pytest_smoke_ini(str(cfg))
    assert any("missing [pytest] section" in err for err in errors)


def test_validate_pytest_smoke_ini_rejects_missing_addopts(tmp_path) -> None:
    cfg = tmp_path / "pytest.smoke.ini"
    cfg.write_text("[pytest]\n", encoding="utf-8")
    errors = _validate_pytest_smoke_ini(str(cfg))
    assert any("missing required 'addopts = -q'" in err for err in errors)


def test_run_preflight_deduplicates_missing_files_in_output(capsys) -> None:
    rc = run_preflight(
        required_modules=[],
        required_files=[
            "backend/tests/__definitely_missing_file_dup__.txt",
            "backend/tests/__definitely_missing_file_dup__.txt",
        ],
    )
    captured = capsys.readouterr()
    assert rc == 2
    details = _extract_details_json(captured.out)
    assert details["missing_count"] == 1
    assert details["missing_files"] == ["backend/tests/__definitely_missing_file_dup__.txt"]


def test_run_preflight_sorts_missing_modules_in_output(capsys) -> None:
    rc = run_preflight(
        required_modules=[
            "zzz_missing_module_for_sort_test",
            "aaa_missing_module_for_sort_test",
        ],
        required_files=[],
    )
    captured = capsys.readouterr()
    assert rc == 2
    line = captured.out.strip().splitlines()[-1]
    assert "aaa_missing_module_for_sort_test" in line
    assert "zzz_missing_module_for_sort_test" in line
    assert line.index("aaa_missing_module_for_sort_test") < line.index("zzz_missing_module_for_sort_test")


def test_run_preflight_sorts_missing_files_in_output(capsys) -> None:
    rc = run_preflight(
        required_modules=[],
        required_files=[
            "backend/tests/zzz_missing_file_for_sort_test.txt",
            "backend/tests/aaa_missing_file_for_sort_test.txt",
        ],
    )
    captured = capsys.readouterr()
    assert rc == 2
    line = captured.out.strip().splitlines()[-1]
    assert "backend/tests/aaa_missing_file_for_sort_test.txt" in line
    assert "backend/tests/zzz_missing_file_for_sort_test.txt" in line
    assert line.index("backend/tests/aaa_missing_file_for_sort_test.txt") < line.index(
        "backend/tests/zzz_missing_file_for_sort_test.txt"
    )


def test_python_version_support_helper() -> None:
    assert _is_python_version_supported((3, 10)) is True
    assert _is_python_version_supported((3, 11)) is True
    assert _is_python_version_supported((3, 9)) is False


def test_unique_preserves_order_and_deduplicates() -> None:
    assert _unique(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_unique_handles_empty_input() -> None:
    assert _unique([]) == []


def test_unique_ignores_blank_items() -> None:
    assert _unique(["a", "", "   ", "b", " a "]) == ["a", "b"]


def test_run_preflight_fails_when_python_version_unsupported(monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight_module, "_is_python_version_supported", lambda _v: False)
    rc = run_preflight(required_modules=[], required_files=[])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out.strip().startswith("[preflight_python_version_unsupported] ")
    assert "Python 3.10+ is required" in captured.out
    assert "(details=" in captured.out
    details = _extract_details_json(captured.out)
    assert "current_python_version" in details
    assert "min_python_version" in details


def test_run_preflight_fails_when_pytest_smoke_ini_contract_invalid(monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight_module, "_validate_required_file_contracts", lambda _files: ["x: invalid"])
    rc = run_preflight(required_modules=["pytest"], required_files=[SMOKE_PYTEST_INI_PATH])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out.strip().startswith("[preflight_required_file_contract_invalid] ")
    assert "Invalid required file contract" in captured.out
    assert "(details=" in captured.out
    details = _extract_details_json(captured.out)
    assert details["error_count"] == 1
    assert details["contract_errors"] == ["x: invalid"]


def test_preflight_error_details_is_valid_json_suffix(capsys) -> None:
    rc = run_preflight(
        required_modules=["definitely_missing_module_for_preflight_details_json_test"],
        required_files=[],
    )
    captured = capsys.readouterr()
    assert rc == 2
    details = _extract_details_json(captured.out)
    assert details["missing_count"] == 1
    assert isinstance(details["missing_modules"], list)


@pytest.mark.requires_monorepo
def test_validate_makefile_error_code_guard_blocks_passes_for_repo_makefile() -> None:
    assert _validate_makefile_error_code_guard_blocks(str(repo_path("Makefile"))) == []


@pytest.mark.requires_monorepo
def test_validate_makefile_error_code_guard_blocks_accepts_crlf_makefile(tmp_path) -> None:
    source_text = repo_path("Makefile").read_text(encoding="utf-8")
    makefile_path = tmp_path / "Makefile"
    makefile_path.write_text(source_text.replace("\n", "\r\n"), encoding="utf-8")
    assert _validate_makefile_error_code_guard_blocks(str(makefile_path)) == []


def test_validate_makefile_error_code_guard_blocks_reports_target_drift(tmp_path) -> None:
    makefile_path = tmp_path / "Makefile"
    makefile_path.write_text(
        "\n".join(
            [
                "event-bus-smoke-unit:",
                "\t@echo unit-without-guard-block",
                "event-bus-smoke-contract-guard:",
                "\t@echo guard",
                "event-bus-smoke-contract-guard-validator:",
                "\t@echo validator-without-guard-block",
                "event-bus-smoke-contract-guard-workflow:",
                "\t@echo workflow",
            ]
        ),
        encoding="utf-8",
    )
    errors = _validate_makefile_error_code_guard_blocks(str(makefile_path))
    assert any("event-bus-smoke-unit missing rendered error-code guard test block" in err for err in errors)
    assert any("event-bus-smoke-contract-guard-validator missing rendered error-code guard test block" in err for err in errors)


def test_normalize_newlines_converts_crlf_and_cr_to_lf() -> None:
    text = "a\r\nb\rc\n"
    assert _normalize_newlines(text) == "a\nb\nc\n"


def test_preflight_cli_returns_0_by_default() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        [],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "preflight passed" in result.stdout
    assert "python=" in result.stdout
    assert "min_python=" in result.stdout
    assert "required_modules=" in result.stdout
    assert "required_files=" in result.stdout


def test_preflight_cli_returns_2_for_missing_module_arg() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--module", "definitely_missing_module_for_preflight_cli_test"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout.strip().startswith("[preflight_missing_modules] ")
    assert "Missing python packages" in result.stdout
    assert "(details=" in result.stdout


def test_preflight_cli_returns_2_for_missing_file_arg() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--file", "backend/tests/__definitely_missing_cli_file__.txt"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout.strip().startswith("[preflight_missing_files] ")
    assert "Missing required files" in result.stdout
    assert "(details=" in result.stdout


def test_preflight_cli_accepts_existing_extra_requirements() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--module", "pytest", "--file", "backend/tests/pytest.smoke.ini"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "preflight passed" in result.stdout


def test_preflight_cli_ignores_blank_extra_requirements() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--module", "   ", "--file", "   "],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "preflight passed" in result.stdout


def test_preflight_cli_error_lines_are_code_prefixed() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--module", "definitely_missing_module_for_preflight_cli_error_prefix_test"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    error_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert error_lines
    assert all(line.startswith("[preflight_") for line in error_lines)


def test_preflight_cli_json_success_output() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["schema_version"] == PREFLIGHT_JSON_SCHEMA_VERSION
    assert isinstance(payload["generated_at_ms"], int) and payload["generated_at_ms"] > 0
    assert payload["source"] == "event_bus_smoke_preflight.py"
    assert isinstance(payload["payload_sha256"], str) and len(payload["payload_sha256"]) == 64
    assert payload["ok"] is True
    assert payload["message"] == "EventBus smoke preflight passed"
    assert "details" in payload
    assert payload["details"]["required_modules"] >= 1


def test_preflight_cli_json_failure_output() -> None:
    result = repo_run_python(
        "backend/scripts/event_bus_smoke_preflight.py",
        ["--json", "--module", "definitely_missing_module_for_preflight_cli_json_failure_test"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout.strip())
    assert payload["schema_version"] == PREFLIGHT_JSON_SCHEMA_VERSION
    assert isinstance(payload["generated_at_ms"], int) and payload["generated_at_ms"] > 0
    assert payload["source"] == "event_bus_smoke_preflight.py"
    assert isinstance(payload["payload_sha256"], str) and len(payload["payload_sha256"]) == 64
    assert payload["ok"] is False
    assert payload["code"] == "preflight_missing_modules"
    assert "missing_modules" in payload["details"]


def test_run_preflight_json_contract_error_includes_code_and_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight_module, "_validate_required_file_contracts", lambda _files: ["x: bad", "y: bad"])
    rc = run_preflight(required_modules=["pytest"], required_files=[SMOKE_PYTEST_INI_PATH], json_output=True)
    captured = capsys.readouterr()
    assert rc == 2
    payload = json.loads(captured.out.strip())
    assert payload["ok"] is False
    assert payload["code"] == "preflight_required_file_contract_invalid"
    assert payload["details"]["error_count"] == 2
    assert payload["details"]["contract_errors"] == ["x: bad", "y: bad"]
