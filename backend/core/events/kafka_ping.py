"""
Kafka bootstrap 轻量级连通探测（TCP）

不依赖 aiokafka：对 bootstrap 列表中的 broker 依次尝试建立 TCP 连接，
用于启动阶段发现「配置写了但 broker 不可达」。TLS/SASL 握手不在此验证。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Tuple


def _strip_broker_uri(spec: str) -> str:
    s = spec.strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    return s.split("/")[0].strip()


def parse_kafka_broker_host_port(spec: str) -> Tuple[str, int]:
    """解析单条 broker，如 host:9092、[::1]:9092、PLAINTEXT://host:9092。"""
    s = _strip_broker_uri(spec)
    if s.startswith("["):
        end = s.find("]")
        if end < 0:
            raise ValueError(f"invalid broker address: {spec!r}")
        host = s[1:end]
        rest = s[end + 1 :].lstrip()
        if rest.startswith(":"):
            port = int(rest[1:])
        else:
            port = 9092
        return host, port
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        return host.strip(), int(port_s)
    return s, 9092


TcpConnector = Callable[[str, int], Awaitable[Tuple[Any, Any]]]


async def _default_tcp_connector(host: str, port: int) -> Tuple[Any, Any]:
    return await asyncio.open_connection(host, port)


_tcp_connector: TcpConnector = _default_tcp_connector


def set_kafka_tcp_connector_for_testing(connector: TcpConnector | None) -> None:
    """测试注入 TCP 连接器；None 恢复默认（asyncio.open_connection）。"""
    global _tcp_connector
    _tcp_connector = connector or _default_tcp_connector


async def probe_kafka_bootstrap_tcp(bootstrap_servers: str, *, timeout_seconds: float = 3.0) -> None:
    """
    对 bootstrap 串行尝试 TCP 连接，任一成功即返回；全部失败则抛错。
    """
    parts = [p.strip() for p in (bootstrap_servers or "").split(",") if p.strip()]
    if not parts:
        raise ValueError("empty kafka bootstrap servers")
    timeout = max(0.1, float(timeout_seconds))
    last_exc: Exception | None = None
    for part in parts:
        try:
            host, port = parse_kafka_broker_host_port(part)
        except Exception as exc:
            last_exc = exc
            continue
        try:
            _reader, writer = await asyncio.wait_for(_tcp_connector(host, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return
        except Exception as exc:
            last_exc = exc
            continue
    raise OSError(f"no reachable kafka broker in bootstrap {bootstrap_servers!r}: {last_exc}") from last_exc
