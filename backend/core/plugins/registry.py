import importlib
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from log import logger

from core.events import get_event_bus
from .base import Plugin
from .manifest import PluginManifest


def _plugin_key(name: str, version: str) -> str:
    return f"{name}@{version}"


class PluginRegistry:
    """
    Plugin 注册中心
    负责插件发现、版本化注册、生命周期管理与运行时增删改载。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PluginRegistry, cls).__new__(cls)
            cls._instance._plugins: Dict[str, Plugin] = {}
            cls._instance._default_versions: Dict[str, str] = {}
            cls._instance._sources: Dict[str, str] = {}
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True

    async def _emit_lifecycle_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            await get_event_bus().publish(event_type=event_type, payload=payload, source="plugin_registry")
        except Exception as e:
            logger.debug(f"[PluginRegistry] emit event failed: {e}")

    def register(self, plugin: Plugin, source: Optional[str] = None) -> None:
        """手动注册插件实例（支持同名多版本并存）"""
        key = _plugin_key(plugin.name, plugin.version)
        self._plugins[key] = plugin
        self._default_versions.setdefault(plugin.name, plugin.version)
        if source:
            self._sources[key] = source
        logger.info(f"[PluginRegistry] Registered plugin: {plugin.name} (v{plugin.version})")

    def set_default_version(self, name: str, version: str) -> None:
        if _plugin_key(name, version) not in self._plugins:
            raise ValueError(f"Plugin '{name}@{version}' not registered")
        self._default_versions[name] = version

    def get(self, name: str, version: Optional[str] = None) -> Optional[Plugin]:
        """获取插件实例（可按 name 或 name+version）"""
        if version:
            return self._plugins.get(_plugin_key(name, version))

        default_version = self._default_versions.get(name)
        if default_version:
            return self._plugins.get(_plugin_key(name, default_version))

        matched = [p for k, p in self._plugins.items() if k.startswith(f"{name}@")]
        if len(matched) == 1:
            return matched[0]
        return None

    def list(self, name: Optional[str] = None) -> List[Plugin]:
        plugins = list(self._plugins.values())
        if name:
            plugins = [p for p in plugins if p.name == name]
        return sorted(plugins, key=lambda p: (p.name, p.version))

    def list_meta(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for key, plugin in self._plugins.items():
            out.append(
                {
                    "key": key,
                    "name": plugin.name,
                    "version": plugin.version,
                    "default": self._default_versions.get(plugin.name) == plugin.version,
                    "source": self._sources.get(key, ""),
                    "type": getattr(plugin, "type", "capability"),
                    "stage": getattr(plugin, "stage", "pre"),
                }
            )
        return sorted(out, key=lambda x: (x["name"], x["version"]))

    async def unregister(self, name: str, version: Optional[str] = None) -> bool:
        plugin = self.get(name, version)
        if plugin is None:
            return False

        key = _plugin_key(plugin.name, plugin.version)
        try:
            await plugin.shutdown()
        except Exception as e:
            logger.warning(f"[PluginRegistry] Plugin '{key}' shutdown failed: {e}")

        self._plugins.pop(key, None)
        self._sources.pop(key, None)

        if self._default_versions.get(plugin.name) == plugin.version:
            remain = sorted([p.version for p in self.list(plugin.name)], reverse=True)
            if remain:
                self._default_versions[plugin.name] = remain[0]
            else:
                self._default_versions.pop(plugin.name, None)

        await self._emit_lifecycle_event(
            "plugin.unregistered",
            {"name": plugin.name, "version": plugin.version, "key": key},
        )
        logger.info(f"[PluginRegistry] Unregistered plugin: {key}")
        return True

    async def load_builtin_plugins(self, logger=None, memory=None, model_registry=None):
        builtin_path = Path(__file__).parent / "builtin"
        if not builtin_path.exists():
            return

        for item in builtin_path.iterdir():
            if item.is_dir():
                manifest_file = item / "plugin.json"
                if manifest_file.exists():
                    await self._load_from_manifest(manifest_file, logger, memory, model_registry)

    async def register_from_manifest(self, manifest_path: str, logger=None, memory=None, model_registry=None) -> bool:
        path = Path(manifest_path)
        if not path.exists():
            raise ValueError(f"Manifest not found: {manifest_path}")
        return await self._load_from_manifest(path, logger, memory, model_registry, allow_replace=True)

    async def reload(self, name: str, version: Optional[str] = None, logger=None, memory=None, model_registry=None) -> bool:
        plugin = self.get(name, version)
        if plugin is None:
            return False
        key = _plugin_key(plugin.name, plugin.version)
        source = self._sources.get(key)
        if not source:
            raise ValueError(f"Plugin '{key}' has no manifest source")
        await self.unregister(plugin.name, plugin.version)
        return await self.register_from_manifest(source, logger=logger, memory=memory, model_registry=model_registry)

    async def _load_from_manifest(
        self,
        manifest_path: Path,
        logger=None,
        memory=None,
        model_registry=None,
        allow_replace: bool = False,
    ) -> bool:
        """
        从 manifest 文件加载插件。
        """
        try:
            manifest_raw = await asyncio.to_thread(manifest_path.read_text, encoding="utf-8")
            data = json.loads(manifest_raw)

            manifest = PluginManifest(**data)

            try:
                module_path, class_name = manifest.entry.split(":")
                module = importlib.import_module(module_path)
                plugin_class: Type[Plugin] = getattr(module, class_name)
            except (ImportError, ValueError, AttributeError) as e:
                logger.error(f"[PluginRegistry] Failed to import '{manifest.entry}' from {manifest_path}: {e}")
                raise

            plugin_inst = plugin_class()
            plugin_inst.name = manifest.name
            plugin_inst.version = manifest.version
            plugin_inst.description = manifest.description
            plugin_inst.type = manifest.type
            plugin_inst.stage = manifest.stage
            plugin_inst.input_schema = manifest.input_schema
            plugin_inst.output_schema = manifest.output_schema
            plugin_inst.supported_modes = manifest.supported_modes
            plugin_inst.permissions = manifest.permissions or []

            from .context import PluginContext

            context = PluginContext(logger=logger, memory=memory, registry=model_registry)
            try:
                initialized = await plugin_inst.initialize(context)
                if not initialized:
                    logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' initialization returned False")
                    return False
                if not await plugin_inst.ready():
                    logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' is not ready after initialization")
                    return False
            except Exception as e:
                logger.warning(f"[PluginRegistry] Plugin '{manifest.name}' initialization raised exception: {e}")
                return False

            existing = self.get(plugin_inst.name, plugin_inst.version)
            if existing is not None and not allow_replace:
                logger.warning(f"[PluginRegistry] Plugin '{plugin_inst.name}@{plugin_inst.version}' already exists")
                return False
            if existing is not None:
                await self.unregister(plugin_inst.name, plugin_inst.version)

            self.register(plugin_inst, source=str(manifest_path))
            await self._emit_lifecycle_event(
                "plugin.registered",
                {"name": plugin_inst.name, "version": plugin_inst.version, "manifest_path": str(manifest_path)},
            )
            return True
        except (ImportError, AttributeError, ValueError) as e:
            logger.error(f"[PluginRegistry] Fatal error loading plugin from {manifest_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"[PluginRegistry] Failed to load plugin from {manifest_path}: {e}")
            return False


def get_plugin_registry() -> PluginRegistry:
    return PluginRegistry()
