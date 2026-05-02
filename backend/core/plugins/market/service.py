from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config.settings import settings
from core.plugins.manager import get_plugin_manager
from core.plugins.repository.market_repository import get_plugin_market_repository
from .validator import PluginMarketValidationError, build_signature_digest, validate_manifest_file


def _package_id(name: str, version: str) -> str:
    return f"{name}@{version}"


def _decode_json_field(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


class PluginMarketService:
    def __init__(self) -> None:
        self.repo = get_plugin_market_repository()
        self.manager = get_plugin_manager()

    def publish(
        self,
        *,
        manifest_path: str,
        package_path: Optional[str],
        author: Optional[str],
        signature: Optional[str],
        source: str,
    ) -> Dict[str, Any]:
        manifest = validate_manifest_file(manifest_path)
        name = str(manifest.get("name") or "")
        version = str(manifest.get("version") or "")
        if not name or not version:
            raise PluginMarketValidationError("manifest missing name/version")
        package_id = _package_id(name, version)
        payload = {
            "id": package_id,
            "name": name,
            "version": version,
            "manifest_path": manifest_path,
            "package_path": package_path,
            "description": manifest.get("description"),
            "author": author,
            "source": source,
            "review_status": "pending",
            "visibility": "private",
            "signature": signature,
            "signature_digest": build_signature_digest(signature or "", manifest_path),
            "compatible_gateway_versions": manifest.get("compatible_gateway_versions") or [],
            "permissions": manifest.get("permissions") or [],
            "metadata": {
                "type": manifest.get("type"),
                "stage": manifest.get("stage"),
                "entry": manifest.get("entry"),
            },
        }
        self.repo.upsert_package(payload)
        return {"package_id": package_id, "review_status": "pending"}

    def list_packages(self, review_status: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.repo.list_packages(review_status=review_status)
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "version": row.version,
                    "manifest_path": row.manifest_path,
                    "package_path": row.package_path,
                    "description": row.description,
                    "author": row.author,
                    "source": row.source,
                    "review_status": row.review_status,
                    "visibility": row.visibility,
                    "signature_digest": row.signature_digest,
                    "compatible_gateway_versions": _decode_json_field(row.compatible_gateway_versions, []),
                    "permissions": _decode_json_field(row.permissions_json, []),
                    "metadata": _decode_json_field(row.metadata_json, {}),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
            )
        return out

    def review(self, package_id: str, approve: bool, visibility: str = "public") -> bool:
        status = "approved" if approve else "rejected"
        ok = self.repo.set_review_status(package_id, status)
        if not ok:
            return False
        if approve:
            self.repo.set_visibility(package_id, visibility)
        return True

    async def install(
        self,
        package_id: str,
        *,
        logger=None,
        memory=None,
        model_registry=None,
        installed_by: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        package = self.repo.get_package(package_id)
        if package is None:
            raise PluginMarketValidationError(f"package not found: {package_id}")
        if package.review_status != "approved":
            raise PluginMarketValidationError("package must be approved before install")
        ok = await self.manager.register_from_manifest(
            package.manifest_path,
            logger=logger,
            memory=memory,
            model_registry=model_registry,
            set_default=True,
        )
        if not ok:
            raise PluginMarketValidationError("plugin registration failed")
        self.repo.upsert_installation(
            package_id=package_id,
            name=package.name,
            version=package.version,
            manifest_path=package.manifest_path,
            enabled=True,
            installed_by=installed_by,
            tenant_id=tenant_id,
        )
        return {"package_id": package_id, "installed": True}

    async def set_enabled(
        self,
        package_id: str,
        enabled: bool,
        *,
        logger=None,
        memory=None,
        model_registry=None,
        tenant_id: Optional[str] = None,
    ) -> bool:
        ins = self.repo.get_installation(package_id, tenant_id=tenant_id)
        if ins is None:
            return False
        if enabled:
            await self.manager.register_from_manifest(
                ins.manifest_path,
                logger=logger,
                memory=memory,
                model_registry=model_registry,
                set_default=True,
            )
        else:
            await self.manager.unregister(ins.name, ins.version)
        return self.repo.set_installation_enabled(package_id, enabled, tenant_id=tenant_id)

    def list_installations(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.repo.list_installations(tenant_id=tenant_id)
        return [
            {
                "id": row.id,
                "package_id": row.package_id,
                "name": row.name,
                "version": row.version,
                "manifest_path": row.manifest_path,
                "enabled": bool(row.enabled),
                "installed_by": row.installed_by,
                "installed_at": row.installed_at.isoformat() if row.installed_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "gateway_version": settings.version,
            }
            for row in rows
        ]


_service: Optional[PluginMarketService] = None


def get_plugin_market_service() -> PluginMarketService:
    global _service
    if _service is None:
        _service = PluginMarketService()
    return _service
