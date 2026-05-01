from __future__ import annotations

from typing import Any, Dict, List

from config.settings import settings
from core.plugins.repository.market_repository import get_plugin_market_repository


def build_plugin_compatibility_matrix() -> Dict[str, Any]:
    repo = get_plugin_market_repository()
    gateway_version = str(getattr(settings, "version", "") or "")
    rows = repo.list_packages()
    matrix: List[Dict[str, Any]] = []
    for row in rows:
        compatible_versions = []
        if row.compatible_gateway_versions:
            try:
                import json

                loaded = json.loads(row.compatible_gateway_versions)
                compatible_versions = [str(v) for v in (loaded if isinstance(loaded, list) else [])]
            except Exception:
                compatible_versions = []
        is_compatible = True
        if compatible_versions:
            is_compatible = gateway_version in compatible_versions or any(
                v.endswith(".*") and gateway_version.startswith(v[:-2]) for v in compatible_versions
            )
        matrix.append(
            {
                "package_id": row.id,
                "name": row.name,
                "plugin_version": row.version,
                "gateway_version": gateway_version,
                "compatible_gateway_versions": compatible_versions,
                "compatible": is_compatible,
                "review_status": row.review_status,
                "visibility": row.visibility,
            }
        )
    return {"gateway_version": gateway_version, "count": len(matrix), "items": matrix}
