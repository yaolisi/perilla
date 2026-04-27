#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Mapping

from scripts.event_bus_smoke_json_integrity import canonical_json_sha256
from scripts.event_bus_smoke_summary_keys import KEY_PAYLOAD_SHA256, SUMMARY_PAYLOAD_KEYS_IN_ORDER


class SummaryPayloadKeyMismatchError(ValueError):
    pass


def build_summary_payload(summary_values_by_key: Mapping[str, Any]) -> Dict[str, Any]:
    expected = set(SUMMARY_PAYLOAD_KEYS_IN_ORDER)
    actual = set(summary_values_by_key.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing_keys={','.join(missing)}")
        if extra:
            parts.append(f"extra_keys={','.join(extra)}")
        raise SummaryPayloadKeyMismatchError("summary payload key mismatch: " + "; ".join(parts))
    payload = {key: summary_values_by_key[key] for key in SUMMARY_PAYLOAD_KEYS_IN_ORDER}
    return with_payload_sha256(payload)


def with_payload_sha256(payload: Mapping[str, Any]) -> Dict[str, Any]:
    signed = dict(payload)
    signed.pop(KEY_PAYLOAD_SHA256, None)
    signed[KEY_PAYLOAD_SHA256] = canonical_json_sha256(signed)
    return signed
