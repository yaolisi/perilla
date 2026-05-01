from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.event_bus_smoke_error_codes as error_codes_module
import scripts.event_bus_smoke_preflight as preflight_module
from scripts.event_bus_smoke_json_integrity import canonical_json_sha256
from tests.repo_paths import repo_path, repo_root, repo_subprocess_env
from scripts.event_bus_smoke_error_code_guard_targets import (
    ERROR_CODE_GUARD_TEST_FILES,
    extract_error_code_guard_tests_from_text,
    render_error_code_guard_tests_for_makefile,
)
from scripts.event_bus_smoke_makefile_utils import slice_make_target

pytestmark = pytest.mark.requires_monorepo

VALIDATOR_FILES = (
    "backend/scripts/validate_event_bus_smoke_summary_result.py",
    "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
    "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
)
PREFLIGHT_FILE = "backend/scripts/event_bus_smoke_preflight.py"
SMOKE_RUNTIME_FILES = (
    "backend/scripts/event_bus_dlq_smoke.py",
    "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
    "backend/scripts/event_bus_smoke_preflight.py",
)
SMOKE_CODED_RUNTIME_FILES = (
    "backend/scripts/event_bus_dlq_smoke.py",
    "backend/scripts/event_bus_smoke_preflight.py",
)
RUNTIME_TARGET_SCRIPT_EXPECTATIONS = (
    ("event-bus-smoke", "event-bus-smoke-pytest", ("backend/scripts/event_bus_dlq_smoke.py",)),
    ("event-bus-smoke-preflight", "event-bus-smoke-fast", ("backend/scripts/event_bus_smoke_preflight.py",)),
    (
        "event-bus-smoke-gh-strict-watch",
        "event-bus-smoke-gh-compatible-watch",
        ("backend/scripts/event_bus_smoke_gh_trigger_watch.py",),
    ),
    (
        "event-bus-smoke-gh-compatible-watch",
        "event-bus-smoke-validate-schema-version",
        ("backend/scripts/event_bus_smoke_gh_trigger_watch.py",),
    ),
)
CORE_GOVERNANCE_TEST_FILES = (
    "backend/tests/test_event_bus_smoke_preflight.py",
    "backend/tests/test_event_bus_smoke_json_integrity_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
)


def test_validator_files_list_matches_expected_scope_exactly() -> None:
    expected = {
        "backend/scripts/validate_event_bus_smoke_summary_result.py",
        "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
    }
    assert set(VALIDATOR_FILES) == expected


def test_validator_files_list_is_unique() -> None:
    assert len(VALIDATOR_FILES) == len(set(VALIDATOR_FILES))


def test_validator_files_exist_in_repo() -> None:
    for path in VALIDATOR_FILES:
        assert repo_path(path).exists(), f"missing validator file: {path}"


def test_smoke_runtime_files_list_is_unique_and_exists() -> None:
    assert len(SMOKE_RUNTIME_FILES) == len(set(SMOKE_RUNTIME_FILES))
    for path in SMOKE_RUNTIME_FILES:
        assert repo_path(path).exists(), f"missing smoke runtime file: {path}"


def test_smoke_runtime_files_list_matches_expected_scope_exactly() -> None:
    expected = {
        "backend/scripts/event_bus_dlq_smoke.py",
        "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
        "backend/scripts/event_bus_smoke_preflight.py",
    }
    assert set(SMOKE_RUNTIME_FILES) == expected


def test_smoke_runtime_files_do_not_define_local_err_constants() -> None:
    offenders: dict[str, list[str]] = {}
    for path in SMOKE_RUNTIME_FILES:
        text = repo_path(path).read_text(encoding="utf-8")
        local_err_defs = [line for line in text.splitlines() if line.startswith("ERR_")]
        if local_err_defs:
            offenders[path] = local_err_defs
    assert not offenders, f"runtime files define local ERR_ constants: {offenders}"


def test_smoke_coded_runtime_files_import_shared_error_code_module() -> None:
    import_snippet = "from scripts.event_bus_smoke_error_codes import"
    for path in SMOKE_CODED_RUNTIME_FILES:
        text = repo_path(path).read_text(encoding="utf-8")
        assert import_snippet in text, f"{path} must import shared error code module"


def test_smoke_runtime_files_are_referenced_by_make_targets() -> None:
    makefile = repo_path("Makefile").read_text(encoding="utf-8")
    covered_paths: set[str] = set()
    for target, next_target, expected_paths in RUNTIME_TARGET_SCRIPT_EXPECTATIONS:
        section = slice_make_target(makefile, target, next_target)
        for expected_path in expected_paths:
            assert expected_path in section, f"{target} must reference {expected_path}"
            covered_paths.add(expected_path)
    assert covered_paths == set(SMOKE_RUNTIME_FILES)


def test_runtime_target_script_expectations_rows_are_well_formed() -> None:
    rows = list(RUNTIME_TARGET_SCRIPT_EXPECTATIONS)
    row_keys = [(target, next_target) for target, next_target, _paths in rows]
    assert len(row_keys) == len(set(row_keys)), "duplicate (target, next_target) rows in RUNTIME_TARGET_SCRIPT_EXPECTATIONS"
    for _target, _next_target, paths in rows:
        assert paths, "each expectation row must list at least one backend/scripts path"


def _makefile_target_def_line_index(makefile_lines: list[str], target: str) -> int:
    prefix = f"{target}:"
    for idx, line in enumerate(makefile_lines):
        if line.startswith(prefix):
            return idx
    raise AssertionError(f"Makefile missing target definition line starting with {prefix!r}")


def test_runtime_target_script_expectations_follow_makefile_physical_order() -> None:
    makefile_text = repo_path("Makefile").read_text(encoding="utf-8")
    makefile_lines = makefile_text.splitlines()
    for target, next_target, _paths in RUNTIME_TARGET_SCRIPT_EXPECTATIONS:
        i_target = _makefile_target_def_line_index(makefile_lines, target)
        i_next = _makefile_target_def_line_index(makefile_lines, next_target)
        assert i_target < i_next, (
            f"Makefile order drift: expected {target!r} before {next_target!r} "
            f"(lines {i_target + 1} vs {i_next + 1})"
        )


def _extract_backend_script_paths(section: str) -> set[str]:
    paths: set[str] = set()
    for raw_line in section.splitlines():
        line = raw_line.replace("\\", " ").replace('"', " ").replace("'", " ")
        for token in line.split():
            if token.startswith("backend/scripts/") and token.endswith(".py"):
                paths.add(token)
    return paths


def test_runtime_make_target_sections_do_not_reference_unknown_runtime_scripts() -> None:
    makefile = repo_path("Makefile").read_text(encoding="utf-8")
    allowed = set(SMOKE_RUNTIME_FILES)
    for target, next_target, _expected_paths in RUNTIME_TARGET_SCRIPT_EXPECTATIONS:
        section = slice_make_target(makefile, target, next_target)
        section_paths = _extract_backend_script_paths(section)
        unknown = sorted(section_paths - allowed)
        assert not unknown, f"{target} references runtime scripts outside SMOKE_RUNTIME_FILES: {unknown}"


def _extract_error_code_tests(section: str) -> set[str]:
    return set(extract_error_code_guard_tests_from_text(section))


def _extract_error_code_tests_in_order(section: str) -> tuple[str, ...]:
    return extract_error_code_guard_tests_from_text(section)


def test_preflight_required_files_include_all_error_code_guard_tests() -> None:
    required_files = set(preflight_module.DEFAULT_REQUIRED_FILES)
    for test_path in ERROR_CODE_GUARD_TEST_FILES:
        assert test_path in required_files


def test_error_code_guard_test_paths_are_unique() -> None:
    assert len(ERROR_CODE_GUARD_TEST_FILES) == len(set(ERROR_CODE_GUARD_TEST_FILES))


def test_error_code_guard_test_files_exist_in_repo() -> None:
    for test_path in ERROR_CODE_GUARD_TEST_FILES:
        assert repo_path(test_path).exists(), f"missing error-code guard test file: {test_path}"


def test_validators_do_not_use_raw_error_string_appends_or_returns() -> None:
    forbidden_snippets = (
        'errors.append("',
        'return ["',
    )
    for validator_path in VALIDATOR_FILES:
        text = repo_path(validator_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            assert snippet not in text, f"{validator_path} contains raw error string pattern: {snippet}"


def test_validators_import_shared_error_code_module() -> None:
    import_snippet = "from scripts.event_bus_smoke_error_codes import"
    for validator_path in VALIDATOR_FILES:
        text = repo_path(validator_path).read_text(encoding="utf-8")
        assert import_snippet in text, f"{validator_path} must import shared error code module"


def test_validators_do_not_define_local_err_constants() -> None:
    for validator_path in VALIDATOR_FILES:
        text = repo_path(validator_path).read_text(encoding="utf-8")
        local_err_defs = [line for line in text.splitlines() if line.startswith("ERR_")]
        assert not local_err_defs, f"{validator_path} defines local ERR_ constants: {local_err_defs}"


def test_gh_validators_use_shared_json_integrity_helper() -> None:
    gh_validator_files = (
        "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
        "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
    )
    import_snippet = "from scripts.event_bus_smoke_json_integrity import canonical_json_sha256"
    for validator_path in gh_validator_files:
        text = repo_path(validator_path).read_text(encoding="utf-8")
        assert import_snippet in text, f"{validator_path} must import canonical_json_sha256"
        assert "canonical_json_sha256(core_payload)" in text
        assert "hashlib.sha256(" not in text


def test_summary_components_use_shared_json_integrity_helper() -> None:
    summary_files = (
        "backend/scripts/validate_event_bus_smoke_summary_result.py",
        "backend/scripts/event_bus_smoke_summary_payload.py",
    )
    for path in summary_files:
        text = repo_path(path).read_text(encoding="utf-8")
        assert "from scripts.event_bus_smoke_json_integrity import" in text, f"{path} must import shared json integrity helpers"
        assert "canonical_json_sha256" in text
        assert "hashlib.sha256(" not in text


def test_gh_trigger_watch_uses_shared_json_integrity_helper() -> None:
    path = "backend/scripts/event_bus_smoke_gh_trigger_watch.py"
    text = repo_path(path).read_text(encoding="utf-8")
    assert "from scripts.event_bus_smoke_json_integrity import canonical_json_sha256" in text
    assert "canonical_json_sha256(core_payload)" in text
    assert "hashlib.sha256(" not in text


def test_event_bus_smoke_scripts_use_single_hashlib_sha256_source() -> None:
    scripts_dir = repo_path("backend/scripts")
    allowed = {"event_bus_smoke_json_integrity.py"}
    offenders: list[str] = []
    candidate_paths = set(scripts_dir.glob("*event_bus_smoke*.py")) | set(scripts_dir.glob("validate_event_bus_smoke*.py"))
    for path in sorted(candidate_paths):
        text = path.read_text(encoding="utf-8")
        if "hashlib.sha256(" not in text:
            continue
        if path.name in allowed:
            continue
        offenders.append(str(path.relative_to(repo_root())).replace("\\", "/"))
    assert not offenders, f"hashlib.sha256 should only exist in shared json integrity module: {offenders}"


def test_event_bus_smoke_scripts_do_not_import_hashlib_outside_shared_module() -> None:
    scripts_dir = repo_path("backend/scripts")
    allowed = {"event_bus_smoke_json_integrity.py"}
    offenders: list[str] = []
    candidate_paths = set(scripts_dir.glob("*event_bus_smoke*.py")) | set(scripts_dir.glob("validate_event_bus_smoke*.py"))
    for path in sorted(candidate_paths):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "import hashlib" in text:
            offenders.append(str(path.relative_to(repo_root())).replace("\\", "/"))
    assert not offenders, f"hashlib import should only exist in shared json integrity module: {offenders}"


def test_event_bus_smoke_scripts_do_not_inline_canonical_json_hashing_config() -> None:
    scripts_dir = repo_path("backend/scripts")
    allowed = {"event_bus_smoke_json_integrity.py"}
    offenders: list[str] = []
    candidate_paths = set(scripts_dir.glob("*event_bus_smoke*.py")) | set(scripts_dir.glob("validate_event_bus_smoke*.py"))
    for path in sorted(candidate_paths):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if 'sort_keys=True, separators=(",", ":")' in text:
            offenders.append(str(path.relative_to(repo_root())).replace("\\", "/"))
    assert not offenders, f"canonical json hash config should only exist in shared json integrity module: {offenders}"


def test_preflight_required_event_bus_scripts_use_shared_json_integrity_rules() -> None:
    allowed = {"backend/scripts/event_bus_smoke_json_integrity.py"}
    offenders_sha: list[str] = []
    offenders_hashlib_import: list[str] = []
    offenders_canonical_inline: list[str] = []
    required_script_paths = sorted(
        {
            path
            for path in preflight_module.DEFAULT_REQUIRED_FILES
            if path.startswith("backend/scripts/") and path.endswith(".py")
        }
    )
    for script_path in required_script_paths:
        if script_path in allowed:
            continue
        text = repo_path(script_path).read_text(encoding="utf-8")
        if "hashlib.sha256(" in text:
            offenders_sha.append(script_path)
        if "import hashlib" in text:
            offenders_hashlib_import.append(script_path)
        if 'sort_keys=True, separators=(",", ":")' in text:
            offenders_canonical_inline.append(script_path)
    assert not offenders_sha, f"preflight-required scripts should not use hashlib.sha256 directly: {offenders_sha}"
    assert not offenders_hashlib_import, f"preflight-required scripts should not import hashlib directly: {offenders_hashlib_import}"
    assert not offenders_canonical_inline, (
        "preflight-required scripts should not inline canonical json hashing config: "
        f"{offenders_canonical_inline}"
    )


def test_preflight_uses_code_prefixed_error_output_convention() -> None:
    text = repo_path(PREFLIGHT_FILE).read_text(encoding="utf-8")
    assert "[ERR]" not in text
    assert "_with_code(" in text


def test_preflight_imports_shared_error_code_module() -> None:
    text = repo_path(PREFLIGHT_FILE).read_text(encoding="utf-8")
    assert "from scripts.event_bus_smoke_error_codes import" in text


def test_preflight_uses_shared_json_integrity_helper() -> None:
    text = repo_path(PREFLIGHT_FILE).read_text(encoding="utf-8")
    assert "from scripts.event_bus_smoke_json_integrity import" in text
    assert "canonical_json_sha256(payload)" in text
    assert "hashlib.sha256(" not in text


def test_preflight_error_code_constants_are_all_used_in_preflight_script() -> None:
    text = repo_path(PREFLIGHT_FILE).read_text(encoding="utf-8")
    expected_preflight_constant_names = {
        "ERR_PREFLIGHT_PYTHON_VERSION_UNSUPPORTED",
        "ERR_PREFLIGHT_MISSING_MODULES",
        "ERR_PREFLIGHT_MISSING_FILES",
        "ERR_PREFLIGHT_REQUIRED_FILE_CONTRACT_INVALID",
    }
    missing_constants = [name for name in expected_preflight_constant_names if name not in text]
    assert not missing_constants, f"missing expected preflight error code constants in preflight script: {missing_constants}"
    for name in expected_preflight_constant_names:
        value = getattr(error_codes_module, name)
        assert isinstance(value, str) and value.startswith("preflight_")


def test_dlq_smoke_script_uses_shared_smoke_dlq_error_codes() -> None:
    path = "backend/scripts/event_bus_dlq_smoke.py"
    text = repo_path(path).read_text(encoding="utf-8")
    expected_constant_names = {
        "ERR_SMOKE_DLQ_ASSERTION_FAILED",
        "ERR_SMOKE_DLQ_HTTP_STEP",
    }
    assert "from scripts.event_bus_smoke_error_codes import" in text
    for name in expected_constant_names:
        assert name in text, f"{path} must reference {name}"
        value = getattr(error_codes_module, name)
        assert isinstance(value, str) and value.startswith("smoke_dlq_")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _with_sha256(payload: dict[str, object], key: str = "payload_sha256") -> dict[str, object]:
    core = dict(payload)
    core[key] = canonical_json_sha256(core)
    return core


def _assert_cli_error_lines_are_code_prefixed(output: str) -> None:
    error_lines = [line for line in output.splitlines() if line.startswith("- ")]
    assert error_lines, "expected at least one validator error line"
    assert all(line.startswith("- [") for line in error_lines)


def test_summary_validator_cli_error_lines_are_code_prefixed(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    payload = _with_sha256(
        {
            "summary_schema_version": 1,
            "health": "green",
            "health_reason": "all_checks_ok",
            "health_reason_codes": ["all_checks_ok"],
            "preflight_contract_check": "ok",
            "preflight_contract_check_reason": "preflight_passed",
            "preflight_reason_code_known": True,
            "contract_check": "ok",
            "contract_check_reason_code": "schema_match+generated_at_valid",
            "contract_reason_code_known": True,
            "result_schema_version": 1,
            "result_generated_at_ms": 1710000000000,
            "result_file": "event-bus-smoke-result.json",
            "result_file_exists": True,
            "log_file": "event-bus-smoke.log",
            "log_file_exists": True,
            "contract_guard_log_file": "event-bus-smoke-contract-guard.log",
            "contract_guard_log_file_exists": True,
            "contract_guard_sections_seen": ["preflight", 1],
            "contract_guard_status": {
                "preflight": "seen",
                "mapping": "missing",
                "payload": "missing",
                "validator": "missing",
                "workflow": "missing",
            },
        }
    )
    _write_json(path, payload)
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_summary_result.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
        env=repo_subprocess_env(),
    )
    assert result.returncode == 1
    _assert_cli_error_lines_are_code_prefixed(result.stdout)


def test_gh_trigger_validator_cli_error_lines_are_code_prefixed(tmp_path: Path) -> None:
    path = tmp_path / "trigger.json"
    payload = _with_sha256(
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
            "trigger_inputs_audit_file": str(path),
            "run_id": "101",
            "run_url": "https://github.com/org/repo/actions/runs/101",
            "conclusion": "unknown",
            "completed_at_ms": 1710000001000,
            "duration_ms": 1000,
        }
    )
    _write_json(path, payload)
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
        env=repo_subprocess_env(),
    )
    assert result.returncode == 1
    _assert_cli_error_lines_are_code_prefixed(result.stdout)


def test_gh_snapshot_validator_cli_error_lines_are_code_prefixed(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    payload = _with_sha256(
        {
            "schema_version": 1,
            "generated_at_ms": 1710000000000,
            "source": "make event-bus-smoke-write-gh-inputs-json-file",
            "workflow": "",
            "base_url": "http://127.0.0.1:8000",
            "event_type": "agent.status.changed",
            "limit": "20",
            "expected_schema_version": "1",
            "expected_summary_schema_version": "1",
            "summary_schema_mode": "strict",
            "payload_sha256_mode": "strict",
            "result_file_stale_threshold_ms": "600000",
            "file_suffix": "",
        }
    )
    _write_json(path, payload)
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
            "--input",
            str(path),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root(),
        env=repo_subprocess_env(),
    )
    assert result.returncode == 1
    _assert_cli_error_lines_are_code_prefixed(result.stdout)


def test_smoke_unit_target_includes_all_error_code_guard_tests() -> None:
    makefile = repo_path("Makefile").read_text(encoding="utf-8")
    section = slice_make_target(makefile, "event-bus-smoke-unit", "event-bus-smoke-contract-guard")
    assert render_error_code_guard_tests_for_makefile() in section
    positions = []
    for test_path in ERROR_CODE_GUARD_TEST_FILES:
        assert test_path in section
        assert section.count(test_path) == 1
        positions.append(section.find(test_path))
    assert positions == sorted(positions)
    total_occurrences = sum(section.count(test_path) for test_path in ERROR_CODE_GUARD_TEST_FILES)
    assert total_occurrences == len(ERROR_CODE_GUARD_TEST_FILES)
    assert _extract_error_code_tests(section) == set(ERROR_CODE_GUARD_TEST_FILES)
    assert _extract_error_code_tests_in_order(section) == ERROR_CODE_GUARD_TEST_FILES
    first = section.find(ERROR_CODE_GUARD_TEST_FILES[0])
    last = section.find(ERROR_CODE_GUARD_TEST_FILES[-1])
    assert first >= 0 and last >= first
    block = section[first : last + len(ERROR_CODE_GUARD_TEST_FILES[-1])]
    assert _extract_error_code_tests_in_order(block) == ERROR_CODE_GUARD_TEST_FILES


def test_guard_validator_target_includes_all_error_code_guard_tests() -> None:
    makefile = repo_path("Makefile").read_text(encoding="utf-8")
    section = slice_make_target(
        makefile,
        "event-bus-smoke-contract-guard-validator",
        "event-bus-smoke-contract-guard-workflow",
    )
    assert render_error_code_guard_tests_for_makefile() in section
    positions = []
    for test_path in ERROR_CODE_GUARD_TEST_FILES:
        assert test_path in section
        assert section.count(test_path) == 1
        positions.append(section.find(test_path))
    assert positions == sorted(positions)
    total_occurrences = sum(section.count(test_path) for test_path in ERROR_CODE_GUARD_TEST_FILES)
    assert total_occurrences == len(ERROR_CODE_GUARD_TEST_FILES)
    assert _extract_error_code_tests(section) == set(ERROR_CODE_GUARD_TEST_FILES)
    assert _extract_error_code_tests_in_order(section) == ERROR_CODE_GUARD_TEST_FILES
    first = section.find(ERROR_CODE_GUARD_TEST_FILES[0])
    last = section.find(ERROR_CODE_GUARD_TEST_FILES[-1])
    assert first >= 0 and last >= first
    block = section[first : last + len(ERROR_CODE_GUARD_TEST_FILES[-1])]
    assert _extract_error_code_tests_in_order(block) == ERROR_CODE_GUARD_TEST_FILES


def test_smoke_unit_target_includes_core_governance_tests_once_and_ordered() -> None:
    makefile = repo_path("Makefile").read_text(encoding="utf-8")
    section = slice_make_target(makefile, "event-bus-smoke-unit", "event-bus-smoke-contract-guard")
    positions: list[int] = []
    for path in CORE_GOVERNANCE_TEST_FILES:
        assert path in section
        assert section.count(path) == 1
        positions.append(section.find(path))
    assert positions == sorted(positions)
