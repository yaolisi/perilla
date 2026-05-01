"""
统一创建 Redis / Redis Cluster 客户端。

大规模部署时可将 redis_cluster_mode=True，并对 inference_cache_redis_url、
event_bus_redis_url 等配置指向 Cluster 入口（单节点 URL 即可，客户端会发现拓扑）。
"""

from __future__ import annotations

from typing import Any

from config.settings import settings


def create_async_redis_client(url: str, *, decode_responses: bool = True) -> Any:
    """异步 Redis 客户端（standalone 或 Cluster）。"""
    if not (url or "").strip():
        raise ValueError("redis url is empty")
    if getattr(settings, "redis_cluster_mode", False):
        from redis.asyncio.cluster import RedisCluster

        return RedisCluster.from_url(url.strip(), decode_responses=decode_responses)
    from redis.asyncio import Redis

    return Redis.from_url(url.strip(), decode_responses=decode_responses)


def create_sync_redis_client(url: str, *, decode_responses: bool = True) -> Any:
    """同步 Redis 客户端（standalone 或 Cluster）。"""
    if not (url or "").strip():
        raise ValueError("redis url is empty")
    if getattr(settings, "redis_cluster_mode", False):
        from redis.cluster import RedisCluster

        return RedisCluster.from_url(url.strip(), decode_responses=decode_responses)
    import redis as redis_sync

    return redis_sync.Redis.from_url(url.strip(), decode_responses=decode_responses)
