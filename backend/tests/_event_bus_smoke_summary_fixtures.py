from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from scripts.event_bus_smoke_summary_keys import (
    KEY_CONTRACT_CHECK,
    KEY_CONTRACT_GUARD_LOG_FILE,
    KEY_CONTRACT_GUARD_LOG_FILE_EXISTS,
    KEY_CONTRACT_GUARD_SECTIONS_SEEN,
    KEY_CONTRACT_GUARD_STATUS,
    KEY_CONTRACT_REASON_CODE,
    KEY_CONTRACT_REASON_KNOWN,
    KEY_HEALTH,
    KEY_HEALTH_REASON,
    KEY_HEALTH_REASON_CODES,
    KEY_LOG_FILE,
    KEY_LOG_FILE_EXISTS,
    KEY_PAYLOAD_SHA256,
    KEY_PREFLIGHT_CHECK,
    KEY_PREFLIGHT_REASON,
    KEY_PREFLIGHT_REASON_KNOWN,
    KEY_RESULT_FILE,
    KEY_RESULT_FILE_EXISTS,
    KEY_RESULT_GENERATED_AT_MS,
    KEY_RESULT_SCHEMA_VERSION,
    KEY_SUMMARY_SCHEMA_VERSION,
)


def with_payload_hash(payload: Dict[str, Any]) -> Dict[str, Any]:
    core = dict(payload)
    canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core[KEY_PAYLOAD_SHA256] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return core


def rehash_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    core = dict(payload)
    core.pop(KEY_PAYLOAD_SHA256, None)
    return with_payload_hash(core)


def base_summary_payload() -> Dict[str, Any]:
    return with_payload_hash(
        {
            KEY_SUMMARY_SCHEMA_VERSION: 1,
            KEY_HEALTH: "green",
            KEY_HEALTH_REASON: "all_checks_ok",
            KEY_HEALTH_REASON_CODES: ["all_checks_ok"],
            KEY_PREFLIGHT_CHECK: "ok",
            KEY_PREFLIGHT_REASON: "preflight_passed",
            KEY_PREFLIGHT_REASON_KNOWN: True,
            KEY_CONTRACT_CHECK: "ok",
            KEY_CONTRACT_REASON_CODE: "schema_match+generated_at_valid",
            KEY_CONTRACT_REASON_KNOWN: True,
            KEY_RESULT_SCHEMA_VERSION: 1,
            KEY_RESULT_GENERATED_AT_MS: 1710000000000,
            KEY_RESULT_FILE: "event-bus-smoke-result.json",
            KEY_RESULT_FILE_EXISTS: True,
            KEY_LOG_FILE: "event-bus-smoke.log",
            KEY_LOG_FILE_EXISTS: True,
            KEY_CONTRACT_GUARD_LOG_FILE: "event-bus-smoke-contract-guard.log",
            KEY_CONTRACT_GUARD_LOG_FILE_EXISTS: True,
            KEY_CONTRACT_GUARD_SECTIONS_SEEN: ["preflight", "mapping"],
            KEY_CONTRACT_GUARD_STATUS: {
                "preflight": "seen",
                "mapping": "seen",
                "payload": "missing",
                "validator": "missing",
                "workflow": "missing",
            },
        }
    )
