"""客户端主机解析（可选信任 X-Forwarded-For），供限流与审计等复用。"""

from __future__ import annotations

from starlette.requests import Request


def client_host_from_request(request: Request, *, trust_x_forwarded_for: bool) -> str:
    """
    返回客户端主机标识字符串（不含 scheme）。

    trust_x_forwarded_for=False 时忽略 X-Forwarded-For，仅用直连 socket（防公网伪造）。
    """
    if trust_x_forwarded_for:
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if xff:
            return xff
    if request.client:
        return request.client.host
    return ""
