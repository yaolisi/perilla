"""
Feature flags store abstraction (DB-backed).
"""
from __future__ import annotations

from typing import Any, Dict

from core.system.settings_store import get_system_settings_store

_FEATURE_FLAGS_KEY = "featureFlags"


def _key_for_tenant(tenant_id: str | None) -> str:
    t = (tenant_id or "default").strip() or "default"
    return f"{_FEATURE_FLAGS_KEY}:{t}"


def get_feature_flags(tenant_id: str | None = None) -> Dict[str, bool]:
    store = get_system_settings_store()
    raw = store.get_setting(_key_for_tenant(tenant_id), {}) or {}
    out: Dict[str, bool] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str):
                out[k] = bool(v)
    return out


def set_feature_flags(flags: Dict[str, Any], tenant_id: str | None = None) -> Dict[str, bool]:
    normalized: Dict[str, bool] = {}
    for k, v in (flags or {}).items():
        if isinstance(k, str):
            normalized[k] = bool(v)
    store = get_system_settings_store()
    store.set_setting(_key_for_tenant(tenant_id), normalized)
    return normalized
