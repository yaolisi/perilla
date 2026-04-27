from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.plugins.registry import PluginRegistry, get_plugin_registry


class PluginManager:
    """
    运行时插件管理层。
    对外提供注册/卸载/重载/版本切换等统一入口。
    """

    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or get_plugin_registry()

    def list_plugins(self) -> List[Dict[str, Any]]:
        return self.registry.list_meta()

    async def register_from_manifest(
        self,
        manifest_path: str,
        *,
        logger=None,
        memory=None,
        model_registry=None,
        set_default: bool = True,
    ) -> bool:
        ok = await self.registry.register_from_manifest(
            manifest_path,
            logger=logger,
            memory=memory,
            model_registry=model_registry,
        )
        if ok and set_default:
            for meta in self.registry.list_meta():
                if meta.get("source") == manifest_path:
                    self.registry.set_default_version(meta["name"], meta["version"])
                    break
        return ok

    async def unregister(self, name: str, version: Optional[str] = None) -> bool:
        return await self.registry.unregister(name, version)

    async def reload(
        self,
        name: str,
        version: Optional[str] = None,
        *,
        logger=None,
        memory=None,
        model_registry=None,
    ) -> bool:
        return await self.registry.reload(
            name,
            version,
            logger=logger,
            memory=memory,
            model_registry=model_registry,
        )

    def set_default_version(self, name: str, version: str) -> None:
        self.registry.set_default_version(name, version)


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
