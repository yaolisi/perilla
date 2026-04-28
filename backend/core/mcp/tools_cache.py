"""
tools/list 结果短时缓存（按 server_config_id），减轻重复拉起子进程。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
DEFAULT_TTL_SECONDS = 60.0


def get_cached_tools(server_id: str, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> Optional[List[Dict[str, Any]]]:
    entry = _CACHE.get(server_id)
    if not entry:
        return None
    ts, tools = entry
    if time.monotonic() - ts > ttl_seconds:
        _CACHE.pop(server_id, None)
        return None
    return tools


def set_cached_tools(server_id: str, tools: List[Dict[str, Any]]) -> None:
    _CACHE[server_id] = (time.monotonic(), tools)


def invalidate_tools_cache(server_id: str) -> None:
    _CACHE.pop(server_id, None)


def clear_all_tools_cache() -> None:
    _CACHE.clear()
