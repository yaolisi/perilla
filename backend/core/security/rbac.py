"""
平台级 RBAC（增强版）

与 Workflow 资源内 ACL（owner/acl）正交：本模块描述「平台身份」对敏感控制面 API 的访问能力。
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional, Set


class PlatformRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


WRITE_METHODS: Set[str] = {"POST", "PUT", "PATCH", "DELETE"}


def parse_api_key_list(raw: str) -> Set[str]:
    if not raw or not str(raw).strip():
        return set()
    return {x.strip() for x in str(raw).split(",") if x.strip()}


def resolve_role_from_api_key(
    api_key: Optional[str],
    admin_keys: Iterable[str],
    operator_keys: Iterable[str],
    viewer_keys: Iterable[str],
    default_role: PlatformRole,
) -> PlatformRole:
    if not api_key:
        return default_role
    k = api_key.strip()
    if not k:
        return default_role
    if k in admin_keys:
        return PlatformRole.ADMIN
    if k in operator_keys:
        return PlatformRole.OPERATOR
    if k in viewer_keys:
        return PlatformRole.VIEWER
    return default_role


def role_may_access_audit(role: PlatformRole) -> bool:
    return role == PlatformRole.ADMIN


def viewer_http_write_denied(method: str, path: str) -> bool:
    """
    viewer 禁止对控制面执行写操作（及部分敏感前缀上的所有非 GET）。
    """
    m = (method or "").upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return False
    p = path or ""
    if p.startswith("/api/v1/workflows"):
        return True
    if p.startswith("/api/backup"):
        return True
    if p.startswith("/api/model-backups"):
        return True
    if p.startswith("/api/models"):
        return True
    if p.startswith("/api/v1/audit"):
        return True
    return False


def viewer_http_access_denied(method: str, path: str) -> bool:
    """
    viewer 是否应被拒绝：包含写拒绝 + 敏感只读前缀（如 Execution Kernel 事件观测）。
    OPTIONS 放行以便浏览器 CORS 预检。
    """
    if viewer_http_write_denied(method, path):
        return True
    m = (method or "").upper()
    p = path or ""
    if m in ("GET", "HEAD") and p.startswith("/api/events"):
        return True
    return False
