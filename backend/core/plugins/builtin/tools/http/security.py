from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse
import ipaddress
import socket

from config.settings import settings
from core.tools.context import ToolContext


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _host_allowed(host: str, patterns: Iterable[str]) -> bool:
    host_l = host.lower()
    for pat in patterns:
        p = pat.strip().lower()
        if not p:
            continue
        if p == host_l:
            return True
        if p.startswith("*.") and host_l.endswith(p[1:]):
            return True
    return False


def check_http_permission_and_url(url: str, ctx: ToolContext) -> Tuple[bool, Optional[str]]:
    """
    Enforce Local-first defaults for HTTP tools.
    Allowed if:
    - ctx.permissions["net.http"] is True, OR settings.tool_net_http_enabled is True
    And (if allowlist non-empty) host matches allowlist.
    """
    # 1) Permission gate (default deny unless explicitly enabled)
    permitted = bool((ctx.permissions or {}).get("net.http")) or bool(settings.tool_net_http_enabled)
    if not permitted:
        return False, "Permission denied: net.http is disabled (enable via ToolContext.permissions['net.http']=true or settings.tool_net_http_enabled=true)"

    # 2) URL validation
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return False, "Invalid URL scheme (must be http or https)"

    host = parsed.hostname
    if not host:
        return False, "Invalid URL (missing hostname)"

    allowed_hosts = _parse_csv(getattr(settings, "tool_net_http_allowed_hosts", "") or "")
    if not allowed_hosts:
        return False, "HTTP outbound allowlist is empty; configure settings.tool_net_http_allowed_hosts"
    if not _host_allowed(host, allowed_hosts):
        return False, f"Host not allowed by allowlist: {host}"

    def _is_private_target(hostname: str) -> bool:
        try:
            ip = ipaddress.ip_address(hostname)
            return bool(
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
            )
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_unspecified
                    or ip.is_reserved
                ):
                    return True
        except socket.gaierror:
            return False
        except Exception:
            return True
        return False

    if not bool(getattr(settings, "tool_net_http_allow_private_targets", False)):
        if _is_private_target(host):
            return False, f"Target host is private or local address: {host}"

    return True, None

