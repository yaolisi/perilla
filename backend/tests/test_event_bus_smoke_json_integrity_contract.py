from __future__ import annotations

from scripts.event_bus_smoke_json_integrity import canonical_json_sha256


def test_canonical_json_sha256_is_stable_for_same_payload() -> None:
    payload = {"a": 1, "b": "x", "nested": {"k": True}}
    first = canonical_json_sha256(payload)
    second = canonical_json_sha256(payload)
    assert first == second


def test_canonical_json_sha256_is_order_independent_for_dict_keys() -> None:
    payload_a = {"a": 1, "b": 2, "c": {"x": 3, "y": 4}}
    payload_b = {"c": {"y": 4, "x": 3}, "b": 2, "a": 1}
    assert canonical_json_sha256(payload_a) == canonical_json_sha256(payload_b)


def test_canonical_json_sha256_preserves_unicode_semantics() -> None:
    payload = {"text": "中文-emoji-🙂", "value": 7}
    digest = canonical_json_sha256(payload)
    assert isinstance(digest, str)
    assert len(digest) == 64
