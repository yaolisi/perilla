"""
FastAPI 依赖：平台角色与权限
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from config.settings import settings

from core.security.rbac import PlatformRole, role_may_access_audit


def get_platform_role(request: Request) -> PlatformRole:
    role = getattr(request.state, "platform_role", None)
    if isinstance(role, PlatformRole):
        return role
    if role is None:
        return PlatformRole.OPERATOR
    try:
        return PlatformRole(str(role))
    except ValueError:
        return PlatformRole.OPERATOR


def require_audit_reader(request: Request) -> PlatformRole:
    role = get_platform_role(request)
    if not role_may_access_audit(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="audit access denied")
    return role


def require_platform_write(request: Request) -> PlatformRole:
    role = get_platform_role(request)
    if role not in {PlatformRole.ADMIN, PlatformRole.OPERATOR}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="platform write access denied")
    return role


def require_platform_admin(request: Request) -> PlatformRole:
    role = get_platform_role(request)
    if role != PlatformRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="platform admin access denied")
    return role


def require_authenticated_platform_admin(request: Request) -> PlatformRole:
    """
    强制要求请求携带 API Key 且角色为 admin。
    避免在 RBAC 关闭或默认角色回退时出现匿名访问控制面的情况。
    """
    api_key_header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")
    api_key = (request.headers.get(api_key_header) or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing API key in header '{api_key_header}'",
        )
    return require_platform_admin(request)
