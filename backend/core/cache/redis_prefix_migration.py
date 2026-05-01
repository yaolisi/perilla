"""
将 Redis 中品牌迁移前的键前缀 openvitamin:* 重命名为当前 settings 中的前缀。

使用 SCAN + RENAME，幂等：目标键已存在则跳过该源键并打日志。

边界：仅处理 Redis **键（KEY）**。Redis **Pub/Sub 频道名** 不属于键空间，不由本模块迁移；
事件总线频道请依赖配置中的 event_bus_channel_prefix 在新进程中生效。
"""

from __future__ import annotations

from typing import Dict, List, Set

from config.settings import settings
from core.redis_client_factory import create_sync_redis_client
from log import logger

LEGACY_ROOT = "openvitamin:"


def _map_legacy_key_to_new(key: str) -> str | None:
    if not key.startswith(LEGACY_ROOT):
        return None
    pairs: tuple[tuple[str, str], ...] = (
        ("openvitamin:inference", str(getattr(settings, "inference_cache_prefix", "perilla:inference") or "perilla:inference")),
        ("openvitamin:event", str(getattr(settings, "event_bus_channel_prefix", "perilla:event") or "perilla:event")),
        ("openvitamin:kbvec", str(getattr(settings, "kb_vector_snapshot_redis_prefix", "perilla:kbvec") or "perilla:kbvec")),
    )
    for old_head, new_head in pairs:
        if key.startswith(old_head):
            return new_head + key[len(old_head) :]
    return "perilla:" + key[len(LEGACY_ROOT) :]


def _unique_redis_urls() -> List[str]:
    raw_urls = [
        str(getattr(settings, "inference_cache_redis_url", "") or "").strip(),
        str(getattr(settings, "event_bus_redis_url", "") or "").strip(),
    ]
    seen: Set[str] = set()
    out: List[str] = []
    for u in raw_urls:
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def migrate_legacy_openvitamin_keys() -> Dict[str, int]:
    """
    对已配置的每个 Redis 连接执行迁移。

    Returns:
        {"urls": n_urls_processed, "keys_renamed": total_renamed, "keys_skipped_dest_exists": skipped}
    """
    if not getattr(settings, "redis_legacy_openvitamin_prefix_migrate_on_startup", True):
        return {"urls": 0, "keys_renamed": 0, "keys_skipped_dest_exists": 0}
    if getattr(settings, "redis_cluster_mode", False):
        # RENAME 在 Cluster 中要求同 hash slot，批量迁移易失败；由运维或独立脚本处理。
        logger.info("[RedisMigrate] skip legacy openvitamin migration when redis_cluster_mode=True")
        return {"urls": 0, "keys_renamed": 0, "keys_skipped_dest_exists": 0}

    urls = _unique_redis_urls()
    total_renamed = 0
    total_skip = 0
    processed = 0

    for url in urls:
        try:
            client = create_sync_redis_client(url, decode_responses=True)
        except Exception as exc:
            logger.warning("[RedisMigrate] skip url=%s (connect failed): %s", url, exc)
            continue

        processed += 1
        cursor = 0
        try:
            while True:
                cursor, keys = client.scan(cursor=cursor, match=f"{LEGACY_ROOT}*", count=256)
                for key in keys:
                    new_key = _map_legacy_key_to_new(key)
                    if not new_key or new_key == key:
                        continue
                    try:
                        if client.exists(new_key):
                            total_skip += 1
                            logger.debug(
                                "[RedisMigrate] dest exists, skip src=%s (keeping dest=%s)",
                                key,
                                new_key,
                            )
                            continue
                        client.rename(key, new_key)
                        total_renamed += 1
                    except Exception as exc:
                        logger.warning("[RedisMigrate] rename failed %s -> %s: %s", key, new_key, exc)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("[RedisMigrate] scan/rename failed url=%s: %s", url, exc)

    if total_renamed or total_skip:
        logger.info(
            "[RedisMigrate] openvitamin:* -> perilla:* urls=%s renamed=%s skipped_dest_exists=%s",
            processed,
            total_renamed,
            total_skip,
        )

    return {"urls": processed, "keys_renamed": total_renamed, "keys_skipped_dest_exists": total_skip}
