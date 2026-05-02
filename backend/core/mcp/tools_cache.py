"""
tools/list 结果短时缓存（按 tenant_id + server_config_id），减轻重复拉起子进程。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

_CACHE: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
DEFAULT_TTL_SECONDS = 60.0


def _eff_tid(tenant_id: Optional[str]) -> str:
    if tenant_id is None:
        return "default"
    return str(tenant_id).strip() or "default"


def _cache_key(server_id: str, tenant_id: Optional[str]) -> Tuple[str, str]:
    return (_eff_tid(tenant_id), server_id)


def get_cached_tools(
    server_id: str,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    *,
    tenant_id: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    key = _cache_key(server_id, tenant_id)
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, tools = entry
    if time.monotonic() - ts > ttl_seconds:
        _CACHE.pop(key, None)
        return None
    return tools


def set_cached_tools(
    server_id: str,
    tools: List[Dict[str, Any]],
    *,
    tenant_id: Optional[str] = None,
) -> None:
    _CACHE[_cache_key(server_id, tenant_id)] = (time.monotonic(), tools)


def invalidate_tools_cache(server_id: str, tenant_id: Optional[str] = None) -> None:
    _CACHE.pop(_cache_key(server_id, tenant_id), None)


def clear_all_tools_cache() -> None:
    _CACHE.clear()
