from typing import Dict, Any, Optional
import jsonschema
from jsonschema import ValidationError
from log import logger
from .registry import PluginRegistry, get_plugin_registry
from .context import PluginContext
from core.security.plugin_policy import evaluate_plugin_permissions

class PluginExecutor:
    """
    Plugin 执行器
    负责插件的调用、Schema 校验与安全性检查
    """
    def __init__(self, registry: Optional[PluginRegistry] = None):
        self.registry = registry or get_plugin_registry()

    def _check_permissions(self, plugin, context: PluginContext) -> bool:
        """
        检查插件权限
        :param plugin: 插件实例
        :param context: 运行上下文
        :return: 是否有权限
        
        说明：
        - 无声明权限：允许执行
        - 声明了权限：必须由 context.permissions 显式授予
        """
        decision = evaluate_plugin_permissions(
            required_permissions=getattr(plugin, "permissions", []) or [],
            grants=getattr(context, "permissions", {}) or {},
        )
        if not decision.allowed:
            logger.warning(
                "[PluginExecutor] Permission denied for plugin '%s': missing=%s, user_id=%s, session_id=%s",
                plugin.name,
                decision.missing_permissions,
                context.user_id,
                context.session_id,
            )
        else:
            logger.debug(
                "[PluginExecutor] Permission granted for plugin '%s': required=%s",
                plugin.name,
                getattr(plugin, "permissions", []) or [],
            )
        return decision.allowed

    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any], schema_name: str) -> None:
        """
        验证数据是否符合 JSON Schema
        :param data: 要验证的数据
        :param schema: JSON Schema 定义
        :param schema_name: Schema 名称（用于错误信息）
        :raises ValueError: 如果验证失败
        """
        if not schema:
            return  # 无 Schema 定义，跳过验证
        
        try:
            jsonschema.validate(instance=data, schema=schema)
        except ValidationError as e:
            error_msg = f"Schema validation failed for {schema_name}: {e.message}"
            if e.path:
                error_msg += f" (path: {'/'.join(str(p) for p in e.path)})"
            logger.error(f"[PluginExecutor] {error_msg}")
            raise ValueError(error_msg) from e

    async def execute(
        self,
        name: str,
        input_data: Dict[str, Any],
        context: PluginContext,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行指定名称的插件
        :param name: 插件名称
        :param input_data: 输入数据
        :param context: 运行上下文
        :return: 插件执行结果
        :raises ValueError: 如果插件不存在、权限不足或 Schema 验证失败
        """
        resolved_name = name
        resolved_version = version
        if "@" in name and version is None:
            resolved_name, resolved_version = name.split("@", 1)

        plugin = self.registry.get(resolved_name, resolved_version)
        if not plugin:
            raise ValueError(f"Plugin '{name}' not found")

        # 检查插件是否就绪
        if not await plugin.ready():
            raise RuntimeError(f"Plugin '{name}' is not ready")

        # 权限检查
        if not self._check_permissions(plugin, context):
            required = getattr(plugin, "permissions", []) or []
            raise PermissionError(
                f"Plugin '{name}' permission denied: required={required}, granted={list((context.permissions or {}).keys())}"
            )

        # 输入 Schema 校验
        self._validate_schema(input_data, plugin.input_schema, f"input schema of '{name}'")

        try:
            logger.debug(f"[PluginExecutor] Executing plugin: {name}")
            result = await plugin.execute(input_data, context)
            
            # 输出 Schema 校验
            self._validate_schema(result, plugin.output_schema, f"output schema of '{name}'")
            
            return result
        except ValueError:
            raise
        except PermissionError:
            raise
        except Exception as e:
            # 其他错误，记录并抛出
            logger.error(f"[PluginExecutor] Failed to execute plugin '{name}': {e}", exc_info=True)
            raise

def get_plugin_executor() -> PluginExecutor:
    """获取全局执行器实例"""
    return PluginExecutor()
