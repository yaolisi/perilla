"""
PostgreSQL SQLAlchemy connect_args（同步 psycopg2 / 异步 asyncpg）。

用于主库 core.data.base 与 execution_kernel 等共用一套超时策略。
"""

from __future__ import annotations

from typing import Any


def merge_postgresql_connect_args(database_url: str, *, sync_psycopg: bool) -> dict[str, Any]:
    """
    sync_psycopg=True：create_engine(psycopg2)；False：create_async_engine(asyncpg)。
    非 postgresql URL 返回空 dict。
    """
    url = str(database_url or "").strip()
    if not url.startswith("postgresql"):
        return {}
    try:
        from config.settings import settings
    except Exception:
        return {}

    ct = int(getattr(settings, "db_connect_timeout_seconds", 10) or 10)
    st = int(getattr(settings, "db_statement_timeout_ms", 0) or 0)

    if sync_psycopg:
        out: dict[str, Any] = {}
        if ct > 0:
            out["connect_timeout"] = ct
        if st > 0:
            out["options"] = f"-c statement_timeout={st}"
        return out

    out_async: dict[str, Any] = {}
    if ct > 0:
        out_async["timeout"] = float(ct)
    if st > 0:
        out_async.setdefault("server_settings", {})["statement_timeout"] = str(st)
    return out_async
