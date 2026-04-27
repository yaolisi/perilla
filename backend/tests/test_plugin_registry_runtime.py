import pytest

from core.plugins.base import Plugin
from core.plugins.context import PluginContext
from core.plugins.registry import get_plugin_registry


class _DemoPlugin(Plugin):
    async def execute(self, input, context: PluginContext):
        return {"ok": True}


@pytest.fixture(autouse=True)
def _reset_registry_state():
    registry = get_plugin_registry()
    registry._plugins.clear()  # type: ignore[attr-defined]
    registry._default_versions.clear()  # type: ignore[attr-defined]
    registry._sources.clear()  # type: ignore[attr-defined]
    yield
    registry._plugins.clear()  # type: ignore[attr-defined]
    registry._default_versions.clear()  # type: ignore[attr-defined]
    registry._sources.clear()  # type: ignore[attr-defined]


def _build_plugin(name: str, version: str) -> _DemoPlugin:
    p = _DemoPlugin()
    p.name = name
    p.version = version
    p.description = "demo"
    p.type = "capability"
    p.stage = "pre"
    p.input_schema = {"type": "object"}
    p.output_schema = {"type": "object"}
    p.supported_modes = ["chat"]
    return p


@pytest.mark.asyncio
async def test_plugin_registry_supports_multi_versions_and_default_switch():
    registry = get_plugin_registry()
    v1 = _build_plugin("demo.plugin", "1.0.0")
    v2 = _build_plugin("demo.plugin", "2.0.0")
    registry.register(v1)
    registry.register(v2)

    assert registry.get("demo.plugin").version == "1.0.0"
    assert registry.get("demo.plugin", "2.0.0").version == "2.0.0"

    registry.set_default_version("demo.plugin", "2.0.0")
    assert registry.get("demo.plugin").version == "2.0.0"


@pytest.mark.asyncio
async def test_plugin_registry_unregister_keeps_other_versions():
    registry = get_plugin_registry()
    v1 = _build_plugin("demo.plugin", "1.0.0")
    v2 = _build_plugin("demo.plugin", "2.0.0")
    registry.register(v1)
    registry.register(v2)
    registry.set_default_version("demo.plugin", "2.0.0")

    ok = await registry.unregister("demo.plugin", "2.0.0")
    assert ok is True
    assert registry.get("demo.plugin").version == "1.0.0"
    assert registry.get("demo.plugin", "2.0.0") is None
