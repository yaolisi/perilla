#!/usr/bin/env python3
from __future__ import annotations

KEY_SUMMARY_SCHEMA_VERSION = "summary_schema_version"
KEY_HEALTH = "health"
KEY_HEALTH_REASON = "health_reason"
KEY_HEALTH_REASON_CODES = "health_reason_codes"
KEY_PREFLIGHT_CHECK = "preflight_contract_check"
KEY_PREFLIGHT_REASON = "preflight_contract_check_reason"
KEY_PREFLIGHT_REASON_KNOWN = "preflight_reason_code_known"
KEY_CONTRACT_CHECK = "contract_check"
KEY_CONTRACT_REASON_CODE = "contract_check_reason_code"
KEY_CONTRACT_REASON_KNOWN = "contract_reason_code_known"
KEY_RESULT_SCHEMA_VERSION = "result_schema_version"
KEY_RESULT_GENERATED_AT_MS = "result_generated_at_ms"
KEY_RESULT_FILE = "result_file"
KEY_RESULT_FILE_EXISTS = "result_file_exists"
KEY_LOG_FILE = "log_file"
KEY_LOG_FILE_EXISTS = "log_file_exists"
KEY_CONTRACT_GUARD_LOG_FILE = "contract_guard_log_file"
KEY_CONTRACT_GUARD_LOG_FILE_EXISTS = "contract_guard_log_file_exists"
KEY_CONTRACT_GUARD_SECTIONS_SEEN = "contract_guard_sections_seen"
KEY_CONTRACT_GUARD_STATUS = "contract_guard_status"
KEY_PAYLOAD_SHA256 = "payload_sha256"

SUMMARY_PAYLOAD_KEYS_IN_ORDER = [
    KEY_SUMMARY_SCHEMA_VERSION,
    KEY_HEALTH,
    KEY_HEALTH_REASON,
    KEY_HEALTH_REASON_CODES,
    KEY_PREFLIGHT_CHECK,
    KEY_PREFLIGHT_REASON,
    KEY_PREFLIGHT_REASON_KNOWN,
    KEY_CONTRACT_CHECK,
    KEY_CONTRACT_REASON_CODE,
    KEY_CONTRACT_REASON_KNOWN,
    KEY_RESULT_SCHEMA_VERSION,
    KEY_RESULT_GENERATED_AT_MS,
    KEY_RESULT_FILE,
    KEY_RESULT_FILE_EXISTS,
    KEY_LOG_FILE,
    KEY_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_PAYLOAD_SHA256,
]
