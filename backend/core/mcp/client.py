"""
MCP 客户端 — stdio 传输（asyncio 子进程 + 换行分隔 JSON-RPC）。

约束（AGENTS.md / 本地优先）：
- 不发起任意网络连接；仅用户配置的本地命令行 Server。
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from log import logger

from core.mcp.protocol import (
    DEFAULT_PROTOCOL_VERSION,
    MCPJsonRpcError,
    build_notification,
    build_request,
    decode_message_line,
    encode_message,
    initialize_params,
    raise_if_error_payload,
)


class MCPStdioClient:
    """
    与单个 MCP Server 进程的一条 stdio 会话。

    用法：
        client = MCPStdioClient(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        await client.connect()
        tools = await client.list_tools()
        await client.call_tool("read_file", {"path": "/tmp/x"})
        await client.close()
    """

    def __init__(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        request_timeout: float = 60.0,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
    ) -> None:
        if not command:
            raise ValueError("command must be non-empty")
        self._command = command
        self._cwd = cwd
        self._extra_env = env or {}
        self._request_timeout = request_timeout
        self._protocol_version = protocol_version

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._negotiated_protocol_version: Optional[str] = None

    @property
    def negotiated_protocol_version(self) -> Optional[str]:
        return self._negotiated_protocol_version

    def _merge_env(self) -> Dict[str, str]:
        merged = dict(os.environ)
        merged.update(self._extra_env)
        return merged

    async def connect(self) -> None:
        if self._proc is not None:
            return
        logger.info("[MCP] starting server: %s", self._command)
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=self._merge_env(),
        )
        assert self._proc.stdin and self._proc.stdout
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        self._reader_task = asyncio.create_task(self._read_stdout_loop())
        await self._handshake()

    async def _handshake(self) -> None:
        init_result = await self.request(
            "initialize",
            initialize_params(self._protocol_version, {}),
        )
        if isinstance(init_result, dict):
            self._negotiated_protocol_version = str(
                init_result.get("protocolVersion") or self._protocol_version
            )
        await self.notify("notifications/initialized", {})

    async def close(self) -> None:
        self._closed = True
        for _mid, fut in list(self._pending.items()):
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None
        if self._proc:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            except ProcessLookupError:
                pass
            self._proc = None

    async def __aenter__(self) -> "MCPStdioClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        await self._ensure_connected()
        msg = build_notification(method, params)
        await self._write_message(msg)

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        await self._ensure_connected()
        mid = self._alloc_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending[mid] = fut
        msg = build_request(mid, method, params)
        try:
            await self._write_message(msg)
            raw = await asyncio.wait_for(fut, timeout=self._request_timeout)
            raise_if_error_payload(raw)
            if "result" not in raw:
                raise MCPJsonRpcError(-32603, "missing result in JSON-RPC response")
            return raw["result"]
        finally:
            self._pending.pop(mid, None)

    async def list_tools(self, *, cursor: Optional[str] = None) -> Dict[str, Any]:
        """tools/list，返回服务端 result 对象（含 tools、nextCursor）。"""
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        return await self.request("tools/list", params)

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """tools/call，返回 result。"""
        payload: Dict[str, Any] = {"name": name}
        if arguments is not None:
            payload["arguments"] = arguments
        return await self.request("tools/call", payload)

    async def _ensure_connected(self) -> None:
        if self._proc is None:
            await self.connect()

    async def _write_message(self, msg: Dict[str, Any]) -> None:
        if self._closed or not self._proc or not self._proc.stdin:
            raise RuntimeError("MCP client is not connected")
        data = encode_message(msg)
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    async def _read_stdout_loop(self) -> None:
        assert self._proc and self._proc.stdout
        stdout = self._proc.stdout
        try:
            while True:
                line = await stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = decode_message_line(line)
                except json.JSONDecodeError as e:
                    logger.warning("[MCP] invalid JSON line: %s", e)
                    continue
                if not payload:
                    continue
                self._dispatch_incoming(payload)
        except asyncio.CancelledError:
            raise
        finally:
            # 进程退出时唤醒仍在等待的请求
            for mid, fut in list(self._pending.items()):
                if not fut.done():
                    fut.set_exception(RuntimeError("MCP connection closed"))
            self._pending.clear()

    def _dispatch_incoming(self, payload: Dict[str, Any]) -> None:
        # 响应：带 id + result/error
        if "id" in payload and payload["id"] is not None:
            raw_id = payload["id"]
            try:
                mid = raw_id if isinstance(raw_id, int) else int(str(raw_id))
            except (TypeError, ValueError):
                logger.warning("[MCP] non-integer response id: %r", raw_id)
                return
            fut = self._pending.get(mid)
            if fut and not fut.done():
                fut.set_result(payload)
            else:
                logger.debug("[MCP] unmatched response id=%s", mid)
            return
        # 通知：无 id 或 JSON-RPC notification
        method = payload.get("method")
        if method:
            logger.debug("[MCP] notification: %s", method)

    async def _drain_stderr(self) -> None:
        if not self._proc or not self._proc.stderr:
            return
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                txt = line.decode("utf-8", errors="replace").rstrip()
                if txt:
                    logger.debug("[MCP stderr] %s", txt[:2000])
        except asyncio.CancelledError:
            raise