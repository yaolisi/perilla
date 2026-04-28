"""
MCP 客户端 — Streamable HTTP 传输（JSON-RPC 经 HTTP POST；响应可为 application/json 或 text/event-stream）。

兼容 MCP 规范：若 Streamable POST 初始化返回 400/404/405，则回退到 **HTTP+SSE（2024-11-05）**：
GET 打开 SSE → 首个 `endpoint` 事件给出 POST 消息 URI → JSON-RPC 响应经 SSE `message` 事件送达。

仅连接用户在配置中显式提供的 URL（及可选请求头）。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx

from log import logger

from core.mcp.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    MCPJsonRpcError,
    build_notification,
    build_request,
    initialize_params,
    raise_if_error_payload,
)


def _normalize_session_header(headers: httpx.Headers) -> Optional[str]:
    return (
        headers.get("mcp-session-id")
        or headers.get("Mcp-Session-Id")
        or headers.get("MCP-SESSION-ID")
    )


def _pick_jsonrpc_response(
    text: str,
    expect_id: Any,
) -> Optional[Dict[str, Any]]:
    """从整段响应文本中解析出与 expect_id 匹配的 JSON-RPC envelope。"""
    t = text.strip()
    if not t:
        return None
    # 纯 JSON（无 SSE）
    if t.startswith("{"):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict) and obj.get("id") == expect_id:
                return obj
        except json.JSONDecodeError:
            pass
    # SSE：逐行 data:
    current_data: List[str] = []
    for raw in t.splitlines():
        line = raw.strip()
        if not line:
            if current_data:
                blob = "\n".join(current_data).strip()
                current_data.clear()
                if blob:
                    try:
                        obj = json.loads(blob)
                        if isinstance(obj, dict) and obj.get("id") == expect_id:
                            return obj
                    except json.JSONDecodeError:
                        continue
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            current_data.append(line[5:].lstrip())
        elif current_data:
            current_data.append(line)
    if current_data:
        blob = "\n".join(current_data).strip()
        if blob:
            try:
                obj = json.loads(blob)
                if isinstance(obj, dict) and obj.get("id") == expect_id:
                    return obj
            except json.JSONDecodeError:
                pass
    return None


def _endpoint_label(base_url: str, *, max_path: int = 48) -> str:
    """可观测用的端点摘要（主机 + 路径前缀），避免记录完整查询串。"""
    p = urlparse(base_url.strip())
    host = p.netloc or ""
    path = (p.path or "").rstrip("/")
    if len(path) > max_path:
        path = path[:max_path] + "…"
    return f"{host}{path}" if host else base_url.strip()[:128]


def _summarize_rpc_for_event_bus(rpc: Dict[str, Any]) -> Dict[str, Any]:
    """不包含 params 具体内容，仅结构摘要（隐私）。"""
    out: Dict[str, Any] = {}
    if "id" in rpc:
        out["rpc_id"] = rpc["id"]
    params = rpc.get("params")
    if isinstance(params, dict):
        out["params_keys"] = list(params.keys())[:48]
    elif params is not None:
        out["has_params"] = True
    return out


def _parse_legacy_endpoint_url(data_raw: str) -> str:
    """解析旧版 SSE `endpoint` 事件的 data 字段为 POST 消息 URL。"""
    s = (data_raw or "").strip()
    if not s:
        raise ValueError("empty endpoint event data")
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    try:
        obj: Any = json.loads(s)
        if isinstance(obj, str) and obj.strip():
            return obj.strip()
        if isinstance(obj, dict):
            for k in ("uri", "url", "endpoint"):
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except json.JSONDecodeError:
        pass
    return s


class MCPHttpLegacySseClient:
    """
    2024-11-05 HTTP+SSE：GET 建立 SSE，首个 `endpoint` 指定 POST 基址；
    请求经 POST 发送，响应在 `message` 事件的 JSON-RPC 中（按 id 关联）。
    """

    def __init__(
        self,
        sse_entry_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        request_timeout: float = 60.0,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    ) -> None:
        u = (sse_entry_url or "").strip()
        if not u:
            raise ValueError("sse_entry_url must be non-empty")
        self._sse_entry_url = u
        self._extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self._timeout = httpx.Timeout(request_timeout)
        self._protocol_version = protocol_version
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        self._post_url: Optional[str] = None
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._negotiated_protocol_version: Optional[str] = None
        self._mcp_protocol_version_header = protocol_version
        self._sse_stream_ctx: Optional[Any] = None
        self._sse_resp: Optional[httpx.Response] = None
        self._sse_task: Optional[asyncio.Task[None]] = None
        self._endpoint_ready = asyncio.Event()
        self._closed = False
        self._handshake_done = False

    @property
    def negotiated_protocol_version(self) -> Optional[str]:
        return self._negotiated_protocol_version

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _merge_post_headers(self) -> Dict[str, str]:
        return {
            **self._extra_headers,
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._mcp_protocol_version_header,
        }

    async def _dispatch_sse_event(self, ev: Dict[str, Any]) -> None:
        et = (ev.get("event") or "message").strip().lower()
        lines = ev.get("data_lines") or []
        data_raw = "\n".join(lines).strip()
        if not data_raw:
            return
        if et == "endpoint":
            try:
                self._post_url = _parse_legacy_endpoint_url(data_raw)
            except ValueError as e:
                logger.warning("[MCP HTTP legacy] bad endpoint data: %s", e)
                return
            self._endpoint_ready.set()
            logger.debug("[MCP HTTP legacy] post endpoint=%s", self._post_url[:120])
            return
        if et != "message":
            return
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError:
            logger.warning("[MCP HTTP legacy] invalid JSON in message event")
            return
        if not isinstance(payload, dict):
            return
        raw_id = payload.get("id")
        if raw_id is None:
            return
        try:
            mid = raw_id if isinstance(raw_id, int) else int(str(raw_id))
        except (TypeError, ValueError):
            return
        fut = self._pending.get(mid)
        if fut and not fut.done():
            fut.set_result(payload)

    async def _consume_sse_loop(self) -> None:
        assert self._sse_resp is not None
        current: Dict[str, Any] = {}
        try:
            async for raw_line in self._sse_resp.aiter_lines():
                line = raw_line.rstrip("\r")
                if line == "":
                    await self._dispatch_sse_event(current)
                    current = {}
                    continue
                if line.startswith(":"):
                    continue
                key, sep, val = line.partition(":")
                if not sep:
                    continue
                key_l = key.strip().lower()
                val_s = val.lstrip()
                if key_l == "event":
                    current["event"] = val_s
                elif key_l == "data":
                    current.setdefault("data_lines", []).append(val_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[MCP HTTP legacy] SSE read ended: %s", e)
        finally:
            for _mid, fut in list(self._pending.items()):
                if not fut.done():
                    fut.set_exception(RuntimeError("MCP legacy SSE stream closed"))

    async def connect(self) -> None:
        if self._handshake_done:
            return
        hdrs = {
            **self._extra_headers,
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": self._mcp_protocol_version_header,
        }
        self._sse_stream_ctx = self._client.stream("GET", self._sse_entry_url, headers=hdrs)
        self._sse_resp = await self._sse_stream_ctx.__aenter__()
        self._sse_resp.raise_for_status()
        self._sse_task = asyncio.create_task(self._consume_sse_loop())
        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), timeout=min(60.0, self._timeout.read or 60.0))
        except asyncio.TimeoutError as e:
            raise RuntimeError("MCP legacy: timeout waiting for endpoint SSE event") from e
        if not self._post_url:
            raise RuntimeError("MCP legacy: no endpoint URL from SSE")
        init_result = await self.request(
            "initialize",
            initialize_params(self._protocol_version, {}),
        )
        if isinstance(init_result, dict):
            nv = str(init_result.get("protocolVersion") or self._protocol_version)
            self._negotiated_protocol_version = nv
            self._mcp_protocol_version_header = nv
        await self.notify("notifications/initialized", {})
        self._handshake_done = True

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self._post_url:
            raise RuntimeError("MCP legacy: post URL not ready")
        mid = self._alloc_id()
        msg = build_request(mid, method, params)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending[mid] = fut
        try:
            r = await self._client.post(self._post_url, json=msg, headers=self._merge_post_headers())
            if r.status_code not in (200, 202):
                r.raise_for_status()
            raw = await asyncio.wait_for(fut, timeout=self._timeout.read or 120.0)
            raise_if_error_payload(raw)
            if "result" not in raw:
                raise MCPJsonRpcError(-32603, "missing result in JSON-RPC response")
            return raw["result"]
        finally:
            self._pending.pop(mid, None)

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        if not self._post_url:
            raise RuntimeError("MCP legacy: post URL not ready")
        msg = build_notification(method, params)
        r = await self._client.post(self._post_url, json=msg, headers=self._merge_post_headers())
        if r.status_code not in (200, 202):
            r.raise_for_status()

    async def list_tools(self, *, cursor: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = await self.request("tools/list", params)
        return result if isinstance(result, dict) else {}

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        payload: Dict[str, Any] = {"name": name}
        if arguments is not None:
            payload["arguments"] = arguments
        return await self.request("tools/call", payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._sse_task = None
        if self._sse_stream_ctx is not None:
            try:
                await self._sse_stream_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._sse_stream_ctx = None
            self._sse_resp = None
        await self._client.aclose()


async def create_mcp_http_client(
    base_url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    request_timeout: float = 60.0,
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    emit_server_push_events: bool = True,
) -> Union[MCPHttpClient, MCPHttpLegacySseClient]:
    """
    优先 Streamable HTTP；若初始化 POST 返回 400/404/405，则回退旧版 HTTP+SSE。
    """
    streamable = MCPHttpClient(
        base_url,
        headers=headers,
        request_timeout=request_timeout,
        protocol_version=protocol_version,
        emit_server_push_events=emit_server_push_events,
    )
    try:
        await streamable.connect()
        return streamable
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code not in (400, 404, 405):
            raise
        logger.info(
            "[MCP HTTP] streamable initialize rejected (%s); trying legacy HTTP+SSE",
            code,
        )
        await streamable.close()
        legacy = MCPHttpLegacySseClient(
            base_url,
            headers=headers,
            request_timeout=request_timeout,
            protocol_version=protocol_version,
        )
        await legacy.connect()
        return legacy


class MCPHttpClient:
    """
    Streamable HTTP MCP endpoint（单 URL，POST JSON-RPC）。

    - 请求头：`Accept`、`Content-Type`、`MCP-Protocol-Version`（握手后与协商版本一致）
    - 可选：服务端返回 `Mcp-Session-Id`，后续请求自动附带；若有 Session 则后台 **GET SSE** 收推送（405 表示无 GET 流）
    - SSE 上服务端 JSON-RPC（含 ``method``）会向事件总线发布 ``mcp.streamable.server_rpc``（仅摘要，不含 params 正文）
    - `extra_headers`：常用于 Authorization 等（由用户在 env/headers 中配置）
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        request_timeout: float = 60.0,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        emit_server_push_events: bool = True,
    ) -> None:
        u = (base_url or "").strip()
        if not u:
            raise ValueError("base_url must be non-empty")
        self._base_url = u
        self._extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self._timeout = httpx.Timeout(request_timeout)
        self._protocol_version = protocol_version
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
        self._next_id = 0
        self._session_id: Optional[str] = None
        self._negotiated_protocol_version: Optional[str] = None
        self._mcp_protocol_version_header = protocol_version
        self._closed = False
        self._server_push_task: Optional[asyncio.Task[None]] = None
        self._emit_server_push_events = bool(emit_server_push_events)

    @property
    def negotiated_protocol_version(self) -> Optional[str]:
        return self._negotiated_protocol_version

    async def _emit_server_push_to_event_bus(self, rpc: Dict[str, Any]) -> None:
        if not self._emit_server_push_events:
            return
        method = rpc.get("method")
        if not isinstance(method, str) or not method.strip():
            return
        try:
            from core.events import get_event_bus

            await get_event_bus().publish(
                event_type="mcp.streamable.server_rpc",
                payload={
                    "endpoint_label": _endpoint_label(self._base_url),
                    "method": method,
                    "rpc_summary": _summarize_rpc_for_event_bus(rpc),
                },
                source="mcp_http_client",
            )
        except Exception as e:
            logger.debug("[MCP HTTP] server push event bus publish failed: %s", e)

    def _start_server_push_listener(self) -> None:
        """有 Session 时后台 GET SSE，接收服务端推送（405 则无此能力）。"""
        if self._closed or not (self._session_id or "").strip():
            return
        if self._server_push_task and not self._server_push_task.done():
            return
        self._server_push_task = asyncio.create_task(self._run_server_push_sse())

    async def _dispatch_server_push_sse_event(self, ev: Dict[str, Any]) -> None:
        lines = ev.get("data_lines") or []
        data_raw = "\n".join(lines).strip()
        if not data_raw:
            return
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict) and payload.get("method"):
            logger.debug("[MCP HTTP] server SSE: %s", payload.get("method"))
            await self._emit_server_push_to_event_bus(payload)

    async def _run_server_push_sse(self) -> None:
        sid = (self._session_id or "").strip()
        if not sid:
            return
        hdrs = {
            **self._extra_headers,
            "Accept": "text/event-stream",
            "MCP-Protocol-Version": self._mcp_protocol_version_header,
            "Mcp-Session-Id": sid,
        }
        try:
            async with self._client.stream("GET", self._base_url, headers=hdrs) as resp:
                if resp.status_code == 405:
                    logger.debug("[MCP HTTP] server push GET not offered (405)")
                    return
                if resp.status_code != 200:
                    logger.debug("[MCP HTTP] server push GET status=%s", resp.status_code)
                    return
                ct = (resp.headers.get("content-type") or "").lower()
                if "text/event-stream" not in ct:
                    return
                current: Dict[str, Any] = {}
                async for raw_line in resp.aiter_lines():
                    if self._closed:
                        break
                    line = raw_line.rstrip("\r")
                    if line == "":
                        await self._dispatch_server_push_sse_event(current)
                        current = {}
                        continue
                    if line.startswith(":"):
                        continue
                    key, sep, val = line.partition(":")
                    if not sep:
                        continue
                    key_l = key.strip().lower()
                    val_s = val.lstrip()
                    if key_l == "event":
                        current["event"] = val_s
                    elif key_l == "data":
                        current.setdefault("data_lines", []).append(val_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closed:
                logger.debug("[MCP HTTP] server push SSE ended: %s", e)

    async def _delete_session_best_effort(self) -> None:
        """Streamable HTTP：显式终止会话（规范推荐；405 表示服务端不支持 DELETE）。"""
        sid = (self._session_id or "").strip()
        if not sid:
            return
        hdrs = {
            **self._extra_headers,
            "Accept": "application/json",
            "MCP-Protocol-Version": self._mcp_protocol_version_header,
            "Mcp-Session-Id": sid,
        }
        try:
            r = await self._client.delete(self._base_url, headers=hdrs)
            if r.status_code not in (200, 204, 405):
                logger.debug("[MCP HTTP] session DELETE status=%s", r.status_code)
        except Exception as e:
            logger.debug("[MCP HTTP] session DELETE skipped: %s", e)

    async def close(self) -> None:
        if self._closed:
            return
        if self._server_push_task:
            self._server_push_task.cancel()
            try:
                await self._server_push_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._server_push_task = None
        await self._delete_session_best_effort()
        self._closed = True
        await self._client.aclose()

    async def __aenter__(self) -> "MCPHttpClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _merge_headers(self) -> Dict[str, str]:
        h = {
            **self._extra_headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._mcp_protocol_version_header,
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    async def _post_once(self, msg: Dict[str, Any]) -> str:
        if self._closed:
            raise RuntimeError("MCP HTTP client is closed")
        async with self._client.stream(
            "POST",
            self._base_url,
            json=msg,
            headers=self._merge_headers(),
        ) as resp:
            resp.raise_for_status()
            sid = _normalize_session_header(resp.headers)
            if sid:
                self._session_id = sid.strip()
            body_bytes = await resp.aread()
        return body_bytes.decode("utf-8", errors="replace")

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        mid = self._alloc_id()
        msg = build_request(mid, method, params)
        text = await self._post_once(msg)
        payload = _pick_jsonrpc_response(text, mid)
        if payload is None:
            logger.warning("[MCP HTTP] unmatched response id=%r body_prefix=%s", mid, text[:800])
            raise RuntimeError("MCP HTTP: no JSON-RPC response matching request id")
        raise_if_error_payload(payload)
        if "result" not in payload:
            raise MCPJsonRpcError(-32603, "missing result in JSON-RPC response")
        return payload["result"]

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        msg = build_notification(method, params)
        await self._post_once(msg)

    async def connect(self) -> None:
        init_result = await self.request(
            "initialize",
            initialize_params(self._protocol_version, {}),
        )
        if isinstance(init_result, dict):
            nv = str(init_result.get("protocolVersion") or self._protocol_version)
            self._negotiated_protocol_version = nv
            self._mcp_protocol_version_header = nv
        await self.notify("notifications/initialized", {})
        self._start_server_push_listener()

    async def list_tools(self, *, cursor: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        result = await self.request("tools/list", params)
        return result if isinstance(result, dict) else {}

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        payload: Dict[str, Any] = {"name": name}
        if arguments is not None:
            payload["arguments"] = arguments
        return await self.request("tools/call", payload)
