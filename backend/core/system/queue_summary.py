"""
Unified queue summary helpers.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def build_unified_queue_summary(
    workflow_running: int,
    image_pending: int,
    image_running: int,
    runtime_models: int,
    *,
    tenant_scope: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    tid = (str(tenant_id).strip() or "default") if tenant_id is not None else None
    return {
        "workflow": {"running": max(0, int(workflow_running))},
        "image_generation": {
            "pending": max(0, int(image_pending)),
            "running": max(0, int(image_running)),
        },
        "runtime": {"active_models": max(0, int(runtime_models))},
        "total_load": max(0, int(workflow_running)) + max(0, int(image_pending)) + max(0, int(image_running)),
        "tenant_scope": bool(tenant_scope),
        "tenant_id": tid if tenant_scope else None,
    }
