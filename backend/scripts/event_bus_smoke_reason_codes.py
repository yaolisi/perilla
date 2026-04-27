#!/usr/bin/env python3
from __future__ import annotations

from typing import Iterable, Set, Tuple, TypedDict


PREFLIGHT_REASON_MISSING_PREFLIGHT_LOG = "missing_preflight_log"
PREFLIGHT_REASON_MISSING_REQUIRED_FILES = "missing_required_files"
PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT = "invalid_required_file_contract"
PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES = "missing_python_packages"
PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION = "unsupported_python_version"
PREFLIGHT_REASON_PREFLIGHT_ERROR = "preflight_error"
PREFLIGHT_REASON_PREFLIGHT_PASSED = "preflight_passed"
PREFLIGHT_REASON_MISSING_PREFLIGHT_STATUS = "missing_preflight_status"

CONTRACT_REASON_SCHEMA_MATCH = "schema_match+generated_at_valid"
CONTRACT_REASON_SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
CONTRACT_REASON_MISSING_SCHEMA_VERSION = "missing_schema_version"
CONTRACT_REASON_MISSING_GENERATED_AT_MS = "missing_generated_at_ms"
CONTRACT_REASON_INVALID_GENERATED_AT_MS = "invalid_generated_at_ms"
CONTRACT_REASON_PARSE_ERROR = "parse_error"
CONTRACT_REASON_MISSING_RESULT_FILE = "missing_result_file"
CONTRACT_REASON_UNKNOWN = "unknown"

SNIPPET_MISSING_REQUIRED_FILES = "Missing required files:"
SNIPPET_INVALID_REQUIRED_FILE_CONTRACT = "Invalid required file contract:"
SNIPPET_MISSING_PYTHON_PACKAGES = "Missing python packages:"
SNIPPET_UNSUPPORTED_PYTHON_VERSION = "Python 3.10+ is required"

class ReasonRegistryConfig(TypedDict):
    preflight_codes: Set[str]
    contract_codes: Set[str]
    preflight_error_mapping: Tuple[Tuple[str, str], ...]


REASON_REGISTRY_CONFIG: ReasonRegistryConfig = {
    "preflight_codes": {
        PREFLIGHT_REASON_MISSING_PREFLIGHT_LOG,
        PREFLIGHT_REASON_MISSING_REQUIRED_FILES,
        PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT,
        PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES,
        PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION,
        PREFLIGHT_REASON_PREFLIGHT_ERROR,
        PREFLIGHT_REASON_PREFLIGHT_PASSED,
        PREFLIGHT_REASON_MISSING_PREFLIGHT_STATUS,
    },
    "contract_codes": {
        CONTRACT_REASON_SCHEMA_MATCH,
        CONTRACT_REASON_SCHEMA_VERSION_MISMATCH,
        CONTRACT_REASON_MISSING_SCHEMA_VERSION,
        CONTRACT_REASON_MISSING_GENERATED_AT_MS,
        CONTRACT_REASON_INVALID_GENERATED_AT_MS,
        CONTRACT_REASON_PARSE_ERROR,
        CONTRACT_REASON_MISSING_RESULT_FILE,
        CONTRACT_REASON_UNKNOWN,
    },
    "preflight_error_mapping": (
        (SNIPPET_MISSING_REQUIRED_FILES, PREFLIGHT_REASON_MISSING_REQUIRED_FILES),
        (SNIPPET_INVALID_REQUIRED_FILE_CONTRACT, PREFLIGHT_REASON_INVALID_REQUIRED_FILE_CONTRACT),
        (SNIPPET_MISSING_PYTHON_PACKAGES, PREFLIGHT_REASON_MISSING_PYTHON_PACKAGES),
        (SNIPPET_UNSUPPORTED_PYTHON_VERSION, PREFLIGHT_REASON_UNSUPPORTED_PYTHON_VERSION),
    ),
}

ALLOWED_PREFLIGHT_REASON_CODES = REASON_REGISTRY_CONFIG["preflight_codes"]
ALLOWED_CONTRACT_REASON_CODES = REASON_REGISTRY_CONFIG["contract_codes"]


def preflight_machine_error_lines(preflight_lines: Iterable[str]) -> list[str]:
    """Collect text-mode preflight failure lines (`[preflight_*]` prefix). Used by CI summary and tests."""

    return [ln for ln in preflight_lines if ln.strip().startswith("[preflight_")]


def smoke_dlq_log_error_lines(log_lines: Iterable[str]) -> list[str]:
    """Collect DLQ smoke stderr failure lines: legacy ``[ERR]`` or ``[smoke_dlq_*]`` (CI summary stats)."""

    result: list[str] = []
    for ln in log_lines:
        st = ln.strip()
        if st.startswith("[ERR]") or st.startswith("[smoke_dlq_"):
            result.append(ln)
    return result


def map_preflight_error_to_reason(error_message: str) -> str:
    for snippet, reason_code in REASON_REGISTRY_CONFIG["preflight_error_mapping"]:
        if snippet in error_message:
            return reason_code
    return PREFLIGHT_REASON_PREFLIGHT_ERROR


def build_contract_reason_code(contract_reasons: Iterable[str], contract_ok: bool) -> str:
    if contract_ok:
        return CONTRACT_REASON_SCHEMA_MATCH
    normalized = sorted({value for value in (str(r).strip() for r in contract_reasons) if value})
    return ",".join(normalized) if normalized else CONTRACT_REASON_UNKNOWN


def is_known_preflight_reason_code(code: str) -> bool:
    return str(code).strip() in ALLOWED_PREFLIGHT_REASON_CODES


def find_unknown_contract_reason_codes(reason_code: str) -> list[str]:
    codes = [part.strip() for part in str(reason_code).split(",") if part.strip()]
    return sorted({code for code in codes if code not in ALLOWED_CONTRACT_REASON_CODES})
