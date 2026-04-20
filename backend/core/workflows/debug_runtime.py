"""
Workflow debug runtime helpers.
提取为轻量模块，便于在不加载完整 API 依赖链时做容错测试。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type


async def kernel_debug_snapshot(
    graph_instance_id: str,
    database_cls: Optional[Type] = None,
    graph_adapter: Optional[Type] = None,
) -> Dict[str, Any]:
    try:
        if database_cls is None:
            from execution_kernel.persistence.db import Database

            database_cls = Database
        if graph_adapter is None:
            from core.workflows.runtime.graph_runtime_adapter import GraphRuntimeAdapter

            graph_adapter = GraphRuntimeAdapter
        kernel_db = database_cls()
        return await graph_adapter.extract_execution_result_from_kernel(
            graph_instance_id,
            kernel_db,
        )
    except Exception as e:
        return {"_error": str(e)}


async def recent_events_debug(
    instance_id: Optional[str],
    limit: int = 80,
    database_cls: Optional[Type] = None,
    event_store_cls: Optional[Type] = None,
) -> Any:
    if not instance_id:
        return []
    try:
        if database_cls is None:
            from execution_kernel.persistence.db import Database

            database_cls = Database
        if event_store_cls is None:
            from execution_kernel.events.event_store import EventStore

            event_store_cls = EventStore
        kernel_db = database_cls()
        async with kernel_db.async_session() as session:
            store = event_store_cls(session)
            events = await store.get_latest_events(instance_id, limit=limit)
        out: List[Dict[str, Any]] = []
        for ev in reversed(events):
            et = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)
            out.append(
                {
                    "event_id": ev.event_id,
                    "sequence": ev.sequence,
                    "event_type": et,
                    "timestamp": ev.timestamp,
                    "payload": ev.payload,
                }
            )
        return out
    except Exception as e:
        return [{"_error": str(e)}]
