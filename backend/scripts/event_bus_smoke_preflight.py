#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List

from scripts.event_bus_smoke_error_code_guard_targets import (
    ERROR_CODE_GUARD_TEST_FILES,
    render_error_code_guard_tests_for_makefile,
)
from scripts.event_bus_smoke_error_codes import (
    ERR_PREFLIGHT_MISSING_FILES,
    ERR_PREFLIGHT_MISSING_MODULES,
    ERR_PREFLIGHT_PYTHON_VERSION_UNSUPPORTED,
    ERR_PREFLIGHT_REQUIRED_FILE_CONTRACT_INVALID,
)
from scripts.event_bus_smoke_json_integrity import canonical_json_dumps, canonical_json_sha256
from scripts.event_bus_smoke_makefile_utils import slice_make_target

MIN_PYTHON_VERSION = (3, 10)
PREFLIGHT_JSON_SCHEMA_VERSION = 1
MAKEFILE_PATH = "Makefile"
SMOKE_PYTEST_INI_PATH = "backend/tests/pytest.smoke.ini"
MAKEFILE_ERROR_CODE_GUARD_TARGET_SPECS = (
    ("event-bus-smoke-unit", "event-bus-smoke-contract-guard"),
    ("event-bus-smoke-contract-guard-validator", "event-bus-smoke-contract-guard-workflow"),
)
DEFAULT_REQUIRED_MODULES = ("pytest",)
DEFAULT_REQUIRED_FILES = (
    "backend/scripts/event_bus_smoke_preflight.py",
    "backend/scripts/validate_event_bus_smoke_result.py",
    "backend/scripts/validate_event_bus_smoke_summary_result.py",
    "backend/scripts/event_bus_smoke_error_codes.py",
    "backend/scripts/event_bus_smoke_error_code_guard_targets.py",
    "backend/scripts/event_bus_smoke_json_integrity.py",
    "backend/scripts/event_bus_smoke_makefile_utils.py",
    "backend/scripts/event_bus_smoke_summary_keys.py",
    "backend/scripts/event_bus_smoke_summary_payload.py",
    "backend/scripts/event_bus_smoke_summary_reason_codes.py",
    "backend/scripts/validate_event_bus_smoke_gh_inputs_snapshot.py",
    "backend/scripts/validate_event_bus_smoke_gh_trigger_inputs_audit.py",
    "backend/scripts/event_bus_smoke_gh_constants.py",
    "backend/scripts/event_bus_smoke_gh_trigger_audit_payload.py",
    "backend/scripts/event_bus_smoke_gh_trigger_audit_arg_map.py",
    "backend/scripts/event_bus_smoke_contract_guard_summary.py",
    "backend/scripts/print_event_bus_smoke_contract_guard_status.py",
    "backend/scripts/event_bus_smoke_gh_trigger_watch.py",
    MAKEFILE_PATH,
    SMOKE_PYTEST_INI_PATH,
    "backend/tests/test_event_bus_dlq_smoke_script.py",
    "backend/tests/test_event_bus_smoke_result_contract.py",
    "backend/tests/test_event_bus_smoke_summary_contract.py",
    "backend/tests/test_event_bus_smoke_preflight.py",
    *ERROR_CODE_GUARD_TEST_FILES,
    "backend/tests/test_event_bus_smoke_json_integrity_contract.py",
    "backend/tests/test_event_bus_smoke_summary_payload.py",
    "backend/tests/test_event_bus_smoke_summary_reason_codes.py",
    "backend/tests/test_event_bus_smoke_gh_inputs_snapshot_contract.py",
    "backend/tests/test_event_bus_smoke_workflow_contract_guard_step.py",
    "backend/tests/test_make_event_bus_smoke_gh_trigger_max_age_validation.py",
    "backend/tests/test_make_event_bus_smoke_gh_trigger_expected_conclusion_validation.py",
    "backend/tests/test_make_event_bus_smoke_contract_guard.py",
    "backend/tests/test_make_event_bus_smoke_contract_guard_status_json.py",
    "backend/tests/test_event_bus_smoke_contract_guard_summary.py",
    "backend/tests/test_make_event_bus_smoke_gh_trigger_audit_mapping_contract.py",
    "backend/tests/test_event_bus_smoke_gh_trigger_audit_payload_contract.py",
    "backend/tests/test_event_bus_smoke_gh_trigger_inputs_audit_contract.py",
    "backend/tests/test_event_bus_smoke_external.py",
)


def _find_missing_modules(modules: Iterable[str]) -> List[str]:
    missing = [m for m in _unique(modules) if importlib.util.find_spec(m) is None]
    return sorted(missing)


def _find_missing_files(files: Iterable[str]) -> List[str]:
    missing = [p for p in _unique(files) if not Path(p).exists()]
    return sorted(missing)


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item is None:
            continue
        item = str(item).strip()
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _is_python_version_supported(version_info: tuple[int, int]) -> bool:
    return version_info >= MIN_PYTHON_VERSION


def _validate_pytest_smoke_ini(path: str) -> List[str]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    errors: List[str] = []
    if not re.search(r"(?m)^\s*\[pytest\]\s*$", text):
        errors.append(f"{path}: missing [pytest] section")
    if not re.search(r"(?m)^\s*addopts\s*=\s*-q\s*$", text):
        errors.append(f"{path}: missing required 'addopts = -q'")
    return errors


def _validate_required_file_contracts(required_files: Iterable[str]) -> List[str]:
    errors: List[str] = []
    files = set(_unique(required_files))
    if SMOKE_PYTEST_INI_PATH in files and Path(SMOKE_PYTEST_INI_PATH).exists():
        errors.extend(_validate_pytest_smoke_ini(SMOKE_PYTEST_INI_PATH))
    if MAKEFILE_PATH in files and Path(MAKEFILE_PATH).exists():
        errors.extend(_validate_makefile_error_code_guard_blocks(MAKEFILE_PATH))
    return errors


def _validate_makefile_error_code_guard_blocks(makefile_path: str) -> List[str]:
    expected_block = _normalize_newlines(render_error_code_guard_tests_for_makefile())
    makefile_text = _normalize_newlines(Path(makefile_path).read_text(encoding="utf-8"))
    errors: List[str] = []
    for target, next_target in MAKEFILE_ERROR_CODE_GUARD_TARGET_SPECS:
        try:
            section = slice_make_target(makefile_text, target, next_target)
        except ValueError as exc:
            errors.append(f"{makefile_path}: {exc}")
            continue
        if expected_block not in section:
            errors.append(f"{makefile_path}: {target} missing rendered error-code guard test block")
    return errors


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _with_code(code: str, message: str, details: dict[str, object] | None = None) -> str:
    if not details:
        return f"[{code}] {message}"
    details_json = canonical_json_dumps(details)
    return f"[{code}] {message} (details={details_json})"


def _emit_preflight_error(
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
    json_output: bool = False,
) -> None:
    if json_output:
        payload = {
            "schema_version": PREFLIGHT_JSON_SCHEMA_VERSION,
            "generated_at_ms": int(time.time() * 1000),
            "source": "event_bus_smoke_preflight.py",
            "ok": False,
            "code": code,
            "message": message,
            "details": details or {},
        }
        payload["payload_sha256"] = _payload_sha256(payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(_with_code(code, message, details=details))


def _emit_preflight_ok(
    *,
    current_version: tuple[int, int],
    required_modules_count: int,
    required_files_count: int,
    json_output: bool = False,
) -> None:
    details = {
        "current_python_version": f"{current_version[0]}.{current_version[1]}",
        "min_python_version": f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}",
        "required_modules": required_modules_count,
        "required_files": required_files_count,
    }
    if json_output:
        payload = {
            "schema_version": PREFLIGHT_JSON_SCHEMA_VERSION,
            "generated_at_ms": int(time.time() * 1000),
            "source": "event_bus_smoke_preflight.py",
            "ok": True,
            "message": "EventBus smoke preflight passed",
            "details": details,
        }
        payload["payload_sha256"] = _payload_sha256(payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(
        "[OK] EventBus smoke preflight passed "
        f"(python={details['current_python_version']}, "
        f"min_python={details['min_python_version']}, "
        f"required_modules={required_modules_count}, "
        f"required_files={required_files_count})"
    )


def run_preflight(
    required_modules: Iterable[str] = DEFAULT_REQUIRED_MODULES,
    required_files: Iterable[str] = DEFAULT_REQUIRED_FILES,
    *,
    json_output: bool = False,
) -> int:
    required_modules = _unique(required_modules)
    required_files = _unique(required_files)
    current_version = (sys.version_info.major, sys.version_info.minor)
    if not _is_python_version_supported(current_version):
        _emit_preflight_error(
            ERR_PREFLIGHT_PYTHON_VERSION_UNSUPPORTED,
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}+ is required, got {current_version[0]}.{current_version[1]}",
            details={
                "current_python_version": f"{current_version[0]}.{current_version[1]}",
                "min_python_version": f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}",
            },
            json_output=json_output,
        )
        return 2

    missing_modules = _find_missing_modules(required_modules)
    if missing_modules:
        _emit_preflight_error(
            ERR_PREFLIGHT_MISSING_MODULES,
            f"Missing python packages: {', '.join(missing_modules)}",
            details={"missing_modules": missing_modules, "missing_count": len(missing_modules)},
            json_output=json_output,
        )
        return 2

    missing_files = _find_missing_files(required_files)
    if missing_files:
        _emit_preflight_error(
            ERR_PREFLIGHT_MISSING_FILES,
            f"Missing required files: {', '.join(missing_files)}",
            details={"missing_files": missing_files, "missing_count": len(missing_files)},
            json_output=json_output,
        )
        return 2

    contract_errors = _validate_required_file_contracts(required_files)
    if contract_errors:
        _emit_preflight_error(
            ERR_PREFLIGHT_REQUIRED_FILE_CONTRACT_INVALID,
            f"Invalid required file contract: {'; '.join(contract_errors)}",
            details={"contract_errors": contract_errors, "error_count": len(contract_errors)},
            json_output=json_output,
        )
        return 2

    _emit_preflight_ok(
        current_version=current_version,
        required_modules_count=len(required_modules),
        required_files_count=len(required_files),
        json_output=json_output,
    )
    return 0


def _payload_sha256(payload: dict[str, object]) -> str:
    return canonical_json_sha256(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run EventBus smoke preflight checks")
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Additional required python module name. Can be repeated.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        help="Additional required file path. Can be repeated.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output for both pass/fail results.",
    )
    args = parser.parse_args()

    required_modules = list(DEFAULT_REQUIRED_MODULES) + list(args.module)
    required_files = list(DEFAULT_REQUIRED_FILES) + list(args.file)
    return run_preflight(required_modules=required_modules, required_files=required_files, json_output=args.json)


if __name__ == "__main__":
    sys.exit(main())
