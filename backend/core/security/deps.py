"""
FastAPI 依赖：平台角色与权限
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from config.settings import settings

from core.security.rbac import PlatformRole, role_may_access_audit


def _empty_json_setting(raw: object) -> bool:
    s = (raw if isinstance(raw, str) else "") or ""
    s = s.strip()
    return s in ("", "{}")


def _debug_bootstrap_system_get_allowed(request: Request) -> bool:
    """
    debug 下界面启动必拉的只读 GET（侧边栏 config、指标、浏览目录等）。
    即使配置了 API_KEYS_JSON（仅用于 scope 注册），也不应阻断本地 UI。
    若显式配置了 RBAC_ADMIN_API_KEYS，仍可通过此处放行上述 GET，避免未带 Key 时整页 401。
    """
    if not getattr(settings, "debug", False):
        return False
    if request.method != "GET":
        return False
    path = request.url.path.rstrip("/") or "/"
    if path == "/api/system/config":
        return True
    if request.url.path.startswith("/api/system/config/schema"):
        return True
    if path in (
        "/api/system/metrics",
        "/api/system/browse-directory",
        "/api/system/browse-file",
    ):
        return True
    return False


def local_dev_control_plane_unlocked() -> bool:
    """
    本地开发：debug=True 且未配置 RBAC 管理员密钥列表时，控制面可不携带 X-Api-Key。

    不再将 api_keys_json 视为「已启用平台密钥」——该字段常用于 scope 注册，与是否要求浏览器带 Key 无关。
    上线环境须 debug=False 并配置认证。
    """
    if not getattr(settings, "debug", False):
        return False
    if (getattr(settings, "rbac_admin_api_keys", "") or "").strip():
        return False
    return True


def should_enforce_api_key_scopes() -> bool:
    """显式配置了 API Key 注册或 scope 映射时，对受保护路径强制校验 X-Api-Key 与 scope。"""
    if not _empty_json_setting(getattr(settings, "api_keys_json", "")):
        return True
    if not _empty_json_setting(getattr(settings, "api_key_scopes_json", "")):
        return True
    return False


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

    未配置平台 API Key 的 debug 本地环境（见 local_dev_control_plane_unlocked）视为管理员，以便设置/浏览等控制面在无密钥时仍可用。
    """
    if _debug_bootstrap_system_get_allowed(request):
        return PlatformRole.ADMIN
    if local_dev_control_plane_unlocked():
        return PlatformRole.ADMIN
    api_key_header = getattr(settings, "api_rate_limit_api_key_header", "X-Api-Key")
    api_key = (request.headers.get(api_key_header) or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing API key in header '{api_key_header}'",
        )
    return require_platform_admin(request)
