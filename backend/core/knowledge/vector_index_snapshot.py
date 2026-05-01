from __future__ import annotations

import json
from typing import Dict, List, Optional

from config.settings import settings
from core.redis_client_factory import create_sync_redis_client
from log import logger


class RedisVectorIndexSnapshot:
    """
    Persist KB vector embeddings in Redis for fast table recovery.

    Data layout:
    - key: <prefix>:<kb_id>
    - value: {"<rowid>": [float, ...], ...}
    """

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "kb_vector_snapshot_redis_enabled", False))
        self._redis_url = str(getattr(settings, "inference_cache_redis_url", "") or "").strip()
        self._prefix = str(getattr(settings, "kb_vector_snapshot_redis_prefix", "perilla:kbvec") or "perilla:kbvec")
        self._client = None
        self._init_tried = False

    def _get_client(self):
        if not self._enabled or not self._redis_url:
            return None
        if self._client is not None:
            return self._client
        if self._init_tried:
            return None
        self._init_tried = True
        try:
            self._client = create_sync_redis_client(self._redis_url, decode_responses=True)
            return self._client
        except Exception as exc:
            logger.warning("[KBVectorSnapshot] redis unavailable, disabled: %s", exc)
            return None

    def _key(self, kb_id: str) -> str:
        return f"{self._prefix}:{kb_id}"

    def save_embedding(self, kb_id: str, rowid: int, embedding: List[float]) -> None:
        client = self._get_client()
        if client is None:
            return
        key = self._key(kb_id)
        try:
            raw = client.get(key)
            data: Dict[str, List[float]] = {}
            if raw:
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    data = loaded
            data[str(int(rowid))] = embedding
            client.set(key, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        except Exception as exc:
            logger.debug("[KBVectorSnapshot] save failed key=%s err=%s", key, exc)

    def delete_embeddings(self, kb_id: str, rowids: List[int]) -> None:
        client = self._get_client()
        if client is None or not rowids:
            return
        key = self._key(kb_id)
        try:
            raw = client.get(key)
            if not raw:
                return
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                return
            for rowid in rowids:
                loaded.pop(str(int(rowid)), None)
            client.set(key, json.dumps(loaded, ensure_ascii=False, separators=(",", ":")))
        except Exception as exc:
            logger.debug("[KBVectorSnapshot] delete failed key=%s err=%s", key, exc)

    def load_embeddings(self, kb_id: str) -> Dict[int, List[float]]:
        client = self._get_client()
        if client is None:
            return {}
        key = self._key(kb_id)
        try:
            raw = client.get(key)
            if not raw:
                return {}
            loaded = json.loads(raw)
            if not isinstance(loaded, dict):
                return {}
            out: Dict[int, List[float]] = {}
            for k, v in loaded.items():
                if isinstance(v, list):
                    out[int(k)] = [float(x) for x in v]
            return out
        except Exception as exc:
            logger.debug("[KBVectorSnapshot] load failed key=%s err=%s", key, exc)
            return {}

    def clear_kb(self, kb_id: str) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.delete(self._key(kb_id))
        except Exception as exc:
            logger.debug("[KBVectorSnapshot] clear failed kb_id=%s err=%s", kb_id, exc)


_snapshot_store: Optional[RedisVectorIndexSnapshot] = None


def get_kb_vector_snapshot_store() -> RedisVectorIndexSnapshot:
    global _snapshot_store
    if _snapshot_store is None:
        _snapshot_store = RedisVectorIndexSnapshot()
    return _snapshot_store

