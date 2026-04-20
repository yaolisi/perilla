"""
Unified queue summary helpers.
"""
from __future__ import annotations

from typing import Any, Dict


def build_unified_queue_summary(
    workflow_running: int,
    image_pending: int,
    image_running: int,
    runtime_models: int,
) -> Dict[str, Any]:
    return {
        "workflow": {"running": max(0, int(workflow_running))},
        "image_generation": {
            "pending": max(0, int(image_pending)),
            "running": max(0, int(image_running)),
        },
        "runtime": {"active_models": max(0, int(runtime_models))},
        "total_load": max(0, int(workflow_running)) + max(0, int(image_pending)) + max(0, int(image_running)),
    }
