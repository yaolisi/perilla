"""
API Key scope middleware.
基于配置中的 api_key_scopes_json 对敏感路径进行 scope 校验。
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config.settings import settings
from core.security.deps import should_enforce_api_key_scopes
from core.system.settings_store import get_system_settings_store

REVOKED_API_KEYS_STORE_KEY = "security.api_keys.revoked"


def _parse_scopes(raw: str) -> Dict[str, List[str]]:
    try:
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            return {}
        out: Dict[str, List[str]] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, list):
                out[k] = [str(x) for x in v]
        return out
    except Exception:
        return {}


def _parse_api_key_registry(raw: str) -> Dict[str, Dict[str, Any]]:
    try:
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for api_key, meta in parsed.items():
            if isinstance(api_key, str) and isinstance(meta, dict):
                out[api_key] = meta
        return out
    except Exception:
        return {}


def _parse_csv_set(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


def _is_expired(expires_at: Optional[str]) -> bool:
    if not expires_at:
        return False
    text = expires_at.strip()
    if not text:
        return False
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt < datetime.now(UTC)
    except Exception:
        return False


class _RevokedKeyCache:
    def __init__(self) -> None:
        self._last_load_ts = 0.0
        self._cache: set[str] = set()

    def get(self) -> set[str]:
        now = time.time()
        if now - self._last_load_ts < 5:
            return set(self._cache)
        self._last_load_ts = now
        try:
            value = get_system_settings_store().get_setting(REVOKED_API_KEYS_STORE_KEY, [])
            if isinstance(value, list):
                self._cache = {str(v).strip() for v in value if str(v).strip()}
            else:
                self._cache = set()
        except Exception:
            self._cache = set()
        return set(self._cache)


_revoked_cache = _RevokedKeyCache()


def get_revoked_api_keys() -> List[str]:
    return sorted(_revoked_cache.get())


def revoke_api_key(api_key: str) -> List[str]:
    key = (api_key or "").strip()
    if not key:
        return get_revoked_api_keys()
    current = _revoked_cache.get()
    current.add(key)
    get_system_settings_store().set_setting(REVOKED_API_KEYS_STORE_KEY, sorted(current))
    _revoked_cache._last_load_ts = 0.0  # force reload next call
    return get_revoked_api_keys()


def unrevoke_api_key(api_key: str) -> List[str]:
    key = (api_key or "").strip()
    current = _revoked_cache.get()
    if key in current:
        current.remove(key)
    get_system_settings_store().set_setting(REVOKED_API_KEYS_STORE_KEY, sorted(current))
    _revoked_cache._last_load_ts = 0.0
    return get_revoked_api_keys()


class ApiKeyScopeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")

    def _required_scope(self, method: str, path: str) -> str | None:
        m = method.upper()
        if path.startswith("/api/v1/audit"):
            return "audit:read"
        if path.startswith("/api/v1/chat/completions"):
            return "chat:write" if m in {"POST", "PUT", "PATCH"} else "chat:read"
        if path.startswith("/api/agents"):
            return "agent:write" if m in {"POST", "PUT", "PATCH", "DELETE"} else "agent:read"
        if path.startswith("/api/knowledge-bases"):
            return "knowledge:write" if m in {"POST", "PUT", "PATCH", "DELETE"} else "knowledge:read"
        if path.startswith("/api/v1/workflows") and m in {"POST", "PUT", "PATCH", "DELETE"}:
            return "workflow:write"
        if path.startswith("/api/models") and m in {"POST", "PUT", "PATCH", "DELETE"}:
            return "model:write"
        return None

    def _extract_resource_target(self, path: str) -> Tuple[Optional[str], Optional[str]]:
        segments = [seg for seg in path.split("/") if seg]
        if len(segments) >= 3 and segments[0] == "api" and segments[1] == "agents":
            return "agent_ids", segments[2]
        if (
            len(segments) >= 3
            and segments[0] == "api"
            and segments[1] == "knowledge-bases"
        ):
            return "knowledge_base_ids", segments[2]
        return None, None

    def _resolve_key_meta(self, api_key: str) -> Dict[str, Any]:
        registry = _parse_api_key_registry(getattr(settings, "api_keys_json", "{}"))
        return registry.get(api_key, {})

    def _resolve_scopes(self, api_key: str, meta: Dict[str, Any]) -> List[str]:
        meta_scopes = meta.get("scopes")
        if isinstance(meta_scopes, list):
            return [str(item) for item in meta_scopes]
        scopes_map = _parse_scopes(getattr(settings, "api_key_scopes_json", "{}"))
        return scopes_map.get(api_key, [])

    def _is_revoked(self, api_key: str, meta: Dict[str, Any]) -> bool:
        if bool(meta.get("revoked", False)):
            return True
        if api_key in _parse_csv_set(getattr(settings, "api_key_revoked_list", "")):
            return True
        return api_key in _revoked_cache.get()

    def _resource_allowed(self, meta: Dict[str, Any], resource_name: str, resource_id: str) -> bool:
        resources = meta.get("resources")
        if not isinstance(resources, dict):
            return True
        allowed = resources.get(resource_name)
        if not isinstance(allowed, list) or not allowed:
            return True
        normalized = {str(item).strip() for item in allowed if str(item).strip()}
        if "*" in normalized:
            return True
        return resource_id in normalized

    async def dispatch(self, request: Request, call_next):
        # 未配置 api_keys_json / api_key_scopes_json 时不拦截（本地默认零配置）
        if not should_enforce_api_key_scopes():
            return await call_next(request)

        required = self._required_scope(request.method, request.url.path)
        if not required:
            return await call_next(request)

        api_key = (request.headers.get(self._header) or "").strip()
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "missing api key",
                    "header": self._header,
                },
            )

        meta = self._resolve_key_meta(api_key)
        if self._is_revoked(api_key, meta):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "api key revoked",
                    "path": request.url.path,
                },
            )

        if _is_expired(str(meta.get("expires_at", ""))):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "api key expired",
                    "path": request.url.path,
                },
            )

        scopes = self._resolve_scopes(api_key, meta)
        if required not in scopes and "admin" not in scopes:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "insufficient api key scope",
                    "required_scope": required,
                    "path": request.url.path,
                },
            )

        resource_name, resource_id = self._extract_resource_target(request.url.path)
        if (
            resource_name
            and resource_id
            and "admin" not in scopes
            and not self._resource_allowed(meta, resource_name, resource_id)
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "resource access denied",
                    "resource": resource_name,
                    "resource_id": resource_id,
                    "path": request.url.path,
                },
            )

        request.state.api_key_scopes = scopes
        request.state.api_key_meta = meta
        return await call_next(request)
