"""
对 Prometheus 指标与健康探针跳过 GZip，降低 scrape CPU，并避免部分采集器对压缩响应不兼容。
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Receive, Scope, Send

from middleware.ops_paths import is_ops_probe_or_metrics_path


class SelectiveGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if is_ops_probe_or_metrics_path(path):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)
