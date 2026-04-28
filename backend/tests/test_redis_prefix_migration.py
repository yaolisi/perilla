"""单元测试：Redis 旧前缀键映射逻辑。"""
from __future__ import annotations

import pytest

from config.settings import settings
from core.cache.redis_prefix_migration import _map_legacy_key_to_new


@pytest.fixture
def restore_inference_prefix():
    prev = settings.inference_cache_prefix
    yield
    settings.inference_cache_prefix = prev


@pytest.fixture
def restore_event_prefix():
    prev = settings.event_bus_channel_prefix
    yield
    settings.event_bus_channel_prefix = prev


@pytest.fixture
def restore_kbvec_prefix():
    prev = settings.kb_vector_snapshot_redis_prefix
    yield
    settings.kb_vector_snapshot_redis_prefix = prev


def test_map_legacy_key_non_openvitamin_returns_none() -> None:
    assert _map_legacy_key_to_new("perilla:inference:x") is None
    assert _map_legacy_key_to_new("") is None
    assert _map_legacy_key_to_new("some:key") is None


def test_map_inference_prefix_default_settings() -> None:
    out = _map_legacy_key_to_new("openvitamin:inference:generate:u1")
    assert out == "perilla:inference:generate:u1"


def test_map_inference_prefix_custom(
    restore_inference_prefix: None,
) -> None:
    settings.inference_cache_prefix = "acme:inference"
    assert (
        _map_legacy_key_to_new("openvitamin:inference:generate:u1")
        == "acme:inference:generate:u1"
    )


def test_map_event_prefix_default(restore_event_prefix: None) -> None:
    assert _map_legacy_key_to_new("openvitamin:event:foo") == "perilla:event:foo"


def test_map_kbvec_prefix_default(restore_kbvec_prefix: None) -> None:
    assert _map_legacy_key_to_new("openvitamin:kbvec:kb_1") == "perilla:kbvec:kb_1"


def test_map_fallback_other_under_openvitamin() -> None:
    assert _map_legacy_key_to_new("openvitamin:custom:tail") == "perilla:custom:tail"


def test_map_exact_legacy_inference_head_only(restore_inference_prefix: None) -> None:
    settings.inference_cache_prefix = "perilla:inference"
    assert _map_legacy_key_to_new("openvitamin:inference") == "perilla:inference"
