"""
Trusted Host：对常规 API 校验 Host；对健康/指标路径豁免（兼容 K8s 探针常用 Pod IP Host）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Optional

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from config.settings import settings
from middleware.ops_paths import is_ops_probe_or_metrics_path


def trusted_host_exempt_path_predicate(path: str) -> bool:
    """是否在 Trusted Host 校验前豁免路径（调用时读取 ``settings``，便于测试 monkeypatch）。"""
    if not bool(getattr(settings, "trusted_host_exempt_ops_paths", True)):
        return False
    return is_ops_probe_or_metrics_path(path)


class SelectiveTrustedHostMiddleware(TrustedHostMiddleware):
    """与 Starlette ``TrustedHostMiddleware`` 一致，但对 ``exempt_host_check`` 为真的路径跳过校验。"""

    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: Optional[Sequence[str]] = None,
        *,
        www_redirect: bool = False,
        exempt_host_check: Optional[Callable[[str], bool]] = None,
    ) -> None:
        super().__init__(app, allowed_hosts=allowed_hosts, www_redirect=www_redirect)
        self.exempt_host_check = exempt_host_check or trusted_host_exempt_path_predicate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            if self.exempt_host_check(path):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)
