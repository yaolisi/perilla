from __future__ import annotations

import pytest

from scripts.event_bus_smoke_summary_keys import SUMMARY_PAYLOAD_KEYS_IN_ORDER
from scripts.event_bus_smoke_summary_payload import (
    SummaryPayloadKeyMismatchError,
    build_summary_payload,
    with_payload_sha256,
)


def _base_values() -> dict[str, object]:
    return {key: f"v:{key}" for key in SUMMARY_PAYLOAD_KEYS_IN_ORDER}


def test_build_summary_payload_orders_by_shared_keys() -> None:
    values = _base_values()
    payload = build_summary_payload(values)
    assert list(payload.keys()) == SUMMARY_PAYLOAD_KEYS_IN_ORDER
    for key in SUMMARY_PAYLOAD_KEYS_IN_ORDER:
        if key == "payload_sha256":
            assert isinstance(payload[key], str) and payload[key]
        else:
            assert payload[key] == values[key]


def test_with_payload_sha256_is_stable_when_reapplied() -> None:
    payload = build_summary_payload(_base_values())
    payload_again = with_payload_sha256(payload)
    assert payload_again["payload_sha256"] == payload["payload_sha256"]


def test_build_summary_payload_rejects_missing_keys() -> None:
    values = _base_values()
    values.pop(SUMMARY_PAYLOAD_KEYS_IN_ORDER[0])
    with pytest.raises(SummaryPayloadKeyMismatchError) as exc:
        build_summary_payload(values)
    assert "missing_keys=" in str(exc.value)


def test_build_summary_payload_rejects_extra_keys() -> None:
    values = _base_values()
    values["unexpected_key"] = "x"
    with pytest.raises(SummaryPayloadKeyMismatchError) as exc:
        build_summary_payload(values)
    assert "extra_keys=unexpected_key" in str(exc.value)


def test_build_summary_payload_reports_missing_and_extra_together() -> None:
    values = _base_values()
    missing_key = SUMMARY_PAYLOAD_KEYS_IN_ORDER[0]
    values.pop(missing_key)
    values["unexpected_key"] = "x"
    with pytest.raises(SummaryPayloadKeyMismatchError) as exc:
        build_summary_payload(values)
    text = str(exc.value)
    assert f"missing_keys={missing_key}" in text
    assert "extra_keys=unexpected_key" in text


def test_build_summary_payload_error_message_format_is_stable() -> None:
    values = _base_values()
    missing_a = SUMMARY_PAYLOAD_KEYS_IN_ORDER[0]
    missing_b = SUMMARY_PAYLOAD_KEYS_IN_ORDER[1]
    values.pop(missing_a)
    values.pop(missing_b)
    values["z_extra"] = "z"
    values["a_extra"] = "a"
    with pytest.raises(SummaryPayloadKeyMismatchError) as exc:
        build_summary_payload(values)
    assert "summary payload key mismatch: missing_keys=" in str(exc.value)
    assert "missing_keys=" + ",".join(sorted([missing_a, missing_b])) in str(exc.value)
    assert "extra_keys=a_extra,z_extra" in str(exc.value)
