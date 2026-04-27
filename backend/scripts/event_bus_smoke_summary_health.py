#!/usr/bin/env python3
from __future__ import annotations

from typing import Tuple


def classify_health(
    preflight_check: str,
    preflight_reason: str,
    contract_check: str,
    contract_reason_code: str,
    preflight_reason_known: bool = True,
    contract_reason_code_known: bool = True,
) -> Tuple[str, str]:
    health = "green"
    health_reasons = []
    registry_degraded = (not preflight_reason_known) or (not contract_reason_code_known)
    if preflight_check != "ok":
        health_reasons.append(f"preflight:{preflight_reason or 'unknown'}")
    if contract_check != "ok":
        health_reasons.append(f"contract:{contract_reason_code or 'unknown'}")
    if registry_degraded:
        health_reasons.append("registry:unknown_reason_code_detected")
    if preflight_check != "ok":
        health = "red"
    elif contract_check != "ok" or registry_degraded:
        health = "yellow"
    health_reason = ",".join(health_reasons) if health_reasons else "all_checks_ok"
    return health, health_reason
