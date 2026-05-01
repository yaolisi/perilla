"""redis 客户端工厂（含 Cluster 模式开关）。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

import core.redis_client_factory as factory


def test_create_async_redis_client_standalone(monkeypatch):
    monkeypatch.setattr(factory.settings, "redis_cluster_mode", False, raising=False)
    sentinel = object()

    def fake_from_url(url: str, *, decode_responses: bool = True) -> object:
        assert "redis://127.0.0.1" in url
        assert decode_responses is True
        return sentinel

    mock_aioredis = MagicMock()
    mock_aioredis.Redis.from_url = fake_from_url
    monkeypatch.setitem(sys.modules, "redis.asyncio", mock_aioredis)

    assert factory.create_async_redis_client("redis://127.0.0.1:6379/0") is sentinel


def test_create_async_uses_cluster_when_flag(monkeypatch):
    monkeypatch.setattr(factory.settings, "redis_cluster_mode", True, raising=False)
    sentinel = object()

    def fake_from_url(url: str, *, decode_responses: bool = True) -> object:
        return sentinel

    mock_cluster = MagicMock()
    mock_cluster.RedisCluster.from_url = fake_from_url
    monkeypatch.setitem(sys.modules, "redis.asyncio.cluster", mock_cluster)

    assert factory.create_async_redis_client("redis://127.0.0.1:6379/0") is sentinel


def test_create_sync_redis_client_standalone(monkeypatch):
    monkeypatch.setattr(factory.settings, "redis_cluster_mode", False, raising=False)
    sentinel = object()

    def fake_from_url(url: str, *, decode_responses: bool = True) -> object:
        return sentinel

    mock_redis_pkg = MagicMock()
    mock_redis_pkg.Redis.from_url = fake_from_url
    monkeypatch.setitem(sys.modules, "redis", mock_redis_pkg)

    assert factory.create_sync_redis_client("redis://127.0.0.1:6379/0") is sentinel


def test_create_sync_uses_cluster_when_flag(monkeypatch):
    monkeypatch.setattr(factory.settings, "redis_cluster_mode", True, raising=False)
    sentinel = object()

    def fake_from_url(url: str, *, decode_responses: bool = True) -> object:
        return sentinel

    mock_cluster = MagicMock()
    mock_cluster.RedisCluster.from_url = fake_from_url
    monkeypatch.setitem(sys.modules, "redis.cluster", mock_cluster)

    assert factory.create_sync_redis_client("redis://127.0.0.1:6379/0") is sentinel


def test_empty_url_raises():
    with pytest.raises(ValueError, match="empty"):
        factory.create_async_redis_client("  ")
