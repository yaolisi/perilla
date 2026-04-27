#!/usr/bin/env python3
from __future__ import annotations

REASON_ALL_CHECKS_OK = "all_checks_ok"
REASON_REGISTRY_DEGRADED = "registry:unknown_reason_code_detected"
REASON_SUMMARY_PAYLOAD_KEY_MISMATCH = "summary_payload_key_mismatch"


def is_allowed_health_reason_code(code: str) -> bool:
    if code in {
        REASON_ALL_CHECKS_OK,
        REASON_REGISTRY_DEGRADED,
        REASON_SUMMARY_PAYLOAD_KEY_MISMATCH,
    }:
        return True
    return code.startswith("preflight:") or code.startswith("contract:")
