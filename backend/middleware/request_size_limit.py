"""
可选：限制 HTTP 请求体大小（与 Ingress client_max_body_size 等对齐；0=不启用）。

- Content-Length 大于上限：立即 413，不读 body。
- Content-Length 存在且可解析为整数且不大于上限：信任该声明并透传 ASGI 流（与旧行为一致，由应用层读取）。
- 缺失或非法 Content-Length：预读 body 并累计字节（覆盖部分 chunked / TE），超出则 413 并 drain。

说明：第三类路径会将请求体缓冲至上限以内（内存与上限同量级）；超大上限请结合前置代理。
"""
from __future__ import annotations

import json
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from config.settings import settings
from middleware.ops_paths import is_ops_probe_or_metrics_path


async def _send_json_413(send: Send, limit: int) -> None:
    payload = json.dumps(
        {"detail": "request body too large", "limit_bytes": limit},
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


async def _drain_request_body(receive: Receive) -> None:
    """丢弃上游尚未读完的 body，避免污染 keep-alive 上的后续请求。"""
    try:
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            if msg["type"] == "http.request" and not msg.get("more_body", False):
                return
    except Exception:
        return


class HttpRequestSizeLimitMiddleware:
    """ASGI 中间件：统一处理请求体大小上限。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = int(getattr(settings, "http_max_request_body_bytes", 0) or 0)
        if limit <= 0:
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if is_ops_probe_or_metrics_path(path):
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "GET").upper()
        if method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        raw_cl = (headers.get("content-length") or "").strip()
        declared: int | None = None
        if raw_cl:
            try:
                declared = int(raw_cl)
            except ValueError:
                declared = None

        if declared is not None:
            if declared > limit:
                await _send_json_413(send, limit)
                await _drain_request_body(receive)
                return
            # 合法声明且不超过上限：透传，避免二次缓冲大请求体。
            await self.app(scope, receive, send)
            return

        buffered: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            body = message.get("body") or b""
            if isinstance(body, memoryview):
                body = body.tobytes()
            total += len(body)
            buffered.append(message)
            if total > limit:
                await _send_json_413(send, limit)
                await _drain_request_body(receive)
                return
            if not message.get("more_body", False):
                break

        idx = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal idx
            if idx < len(buffered):
                m = buffered[idx]
                idx += 1
                return m
            return {"type": "http.disconnect"}

        await self.app(scope, replay_receive, send)
