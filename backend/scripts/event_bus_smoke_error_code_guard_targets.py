from __future__ import annotations

import re
from pathlib import Path

ERROR_CODE_GUARD_TEST_GLOB = "test_event_bus_smoke_error_code*.py"
ERROR_CODE_GUARD_TEST_PATH_PREFIX = "backend/tests/"

ERROR_CODE_GUARD_TEST_FILES = (
    "backend/tests/test_event_bus_smoke_error_code_contract.py",
    "backend/tests/test_event_bus_smoke_error_codes_constants_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_preflight_json_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_guard_targets_contract.py",
    "backend/tests/test_event_bus_smoke_error_code_coverage_contract.py",
)


def render_error_code_guard_tests_for_makefile(indent: str = "\t\t") -> str:
    lines = []
    last_index = len(ERROR_CODE_GUARD_TEST_FILES) - 1
    for index, test_path in enumerate(ERROR_CODE_GUARD_TEST_FILES):
        suffix = " \\" if index < last_index else ""
        lines.append(f"{indent}{test_path}{suffix}")
    return "\n".join(lines)


def error_code_guard_test_regex() -> str:
    return re.escape(ERROR_CODE_GUARD_TEST_GLOB).replace(r"\*", ".*")


def error_code_guard_test_path_regex() -> str:
    return rf"{re.escape(ERROR_CODE_GUARD_TEST_PATH_PREFIX)}{error_code_guard_test_regex()}"


def extract_error_code_guard_tests_from_text(text: str) -> tuple[str, ...]:
    pattern = re.compile(error_code_guard_test_path_regex())
    extracted = []
    seen = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for token in stripped.split():
            candidate = token.strip().rstrip("\\").strip()
            if not candidate:
                continue
            if pattern.fullmatch(candidate):
                if candidate in seen:
                    continue
                seen.add(candidate)
                extracted.append(candidate)
    return tuple(extracted)


def discover_error_code_guard_test_files(base_dir: str = "backend/tests") -> tuple[str, ...]:
    discovered = [
        str(path).replace("\\", "/")
        for path in Path(base_dir).glob(ERROR_CODE_GUARD_TEST_GLOB)
    ]
    return tuple(sorted(discovered))
