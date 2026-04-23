from core.tools.registry import ToolRegistry
from .cpu import SystemCpuTool
from .memory import SystemMemoryTool
from .disk import SystemDiskTool
from .env import SystemEnvTool

def register() -> None:
    ToolRegistry.register(SystemCpuTool())
    ToolRegistry.register(SystemMemoryTool())
    ToolRegistry.register(SystemDiskTool())
    ToolRegistry.register(SystemEnvTool())
