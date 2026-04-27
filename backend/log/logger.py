"""
平台统一日志：控制台 + 文件轮转 + 结构化日志

- 标准 logger：支持控制台与按天轮转文件（保留 30 天）
- log_structured：单行 JSON 结构化日志，全平台可用，便于解析与检索
"""
import datetime
import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


def _normalize_level(level_name: str | None, fallback: str = "INFO") -> str:
    candidate = (level_name or "").strip().upper()
    if candidate in _VALID_LOG_LEVELS:
        return candidate
    return fallback


def _resolve_log_level(debug: bool, explicit: str | None = None) -> str:
    if explicit:
        return _normalize_level(explicit, fallback="INFO")
    return "DEBUG" if debug else "INFO"


class StructuredJsonFormatter(logging.Formatter):
    """统一 JSON 日志格式，便于 ELK/Loki 聚合检索。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


class ComponentFilter(logging.Filter):
    """按 component 字段或消息前缀筛选日志记录。"""

    def __init__(self, components: set[str] | None = None, prefixes: tuple[str, ...] = ()) -> None:
        super().__init__()
        self._components = {c.strip().lower() for c in (components or set()) if c.strip()}
        self._prefixes = tuple(prefixes)

    def filter(self, record: logging.LogRecord) -> bool:
        component = str(getattr(record, "component", "") or "").strip().lower()
        message = str(record.getMessage() or "")
        if component and component in self._components:
            return True
        return any(message.startswith(prefix) for prefix in self._prefixes)


def _default_log_dir() -> Path:
    """日志目录：项目根目录/logs（backend/log/logger.py -> backend -> 项目根）"""
    this_file = Path(__file__).resolve()
    backend_dir = this_file.parent.parent  # backend
    root_dir = backend_dir.parent          # 项目根目录
    return root_dir / "logs"


def setup_logger(
    name: str = "ai_platform",
    log_dir: Path | str | None = None,
    file_basename: str = "app.log",
    backup_count: int = 30,
    level: str | None = None,
    debug: bool = True,
    format_type: str = "text",
) -> logging.Logger:
    """
    创建并配置根 logger。

    - 支持 text / json 两种输出格式
    - 日志级别按环境动态切换（开发 DEBUG，生产 INFO）
    - 文件：按天轮转，保留 backup_count 天
    """
    log_dir = Path(log_dir) if log_dir else _default_log_dir()
    log_dir = log_dir.resolve()
    log_file = log_dir / file_basename
    log_file = log_file.resolve()

    if not log_dir.exists():
        os.makedirs(log_dir, exist_ok=True)

    log = logging.getLogger(name)
    log_level = _resolve_log_level(debug=debug, explicit=level)
    log.setLevel(getattr(logging, log_level, logging.INFO))

    if log.handlers:
        log.handlers.clear()

    normalized_format = (format_type or "text").strip().lower()
    if normalized_format == "json":
        formatter: logging.Formatter = StructuredJsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="[%(asctime)s] %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    log.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        atTime=datetime.time(0, 0, 0),
    )
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    # 核心模块独立日志文件，便于模块级快速排障。
    module_handlers: list[tuple[str, ComponentFilter]] = [
        (
            "inference.log",
            ComponentFilter(
                components={"inferencegateway", "providerruntimeadapter", "runtimestabilization"},
                prefixes=("[InferenceGateway]", "[ProviderRuntimeAdapter]"),
            ),
        ),
        (
            "agent_runtime.log",
            ComponentFilter(
                components={"runtime", "planbasedexecutor", "agentloop", "agentruntime"},
                prefixes=("[AgentRuntime]", "[PlanBasedExecutor]", "[AgentLoop]"),
            ),
        ),
    ]
    for module_file, module_filter in module_handlers:
        module_handler = TimedRotatingFileHandler(
            filename=str((log_dir / module_file).resolve()),
            when="midnight",
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
            atTime=datetime.time(0, 0, 0),
        )
        module_handler.setFormatter(formatter)
        module_handler.addFilter(module_filter)
        log.addHandler(module_handler)

    log.propagate = False
    return log


# 全局 logger 实例
logger = setup_logger()


def log_structured(
    component: str,
    event: str,
    level: str = "info",
    **kwargs: Any,
) -> None:
    """
    输出结构化日志，全平台可用。

    格式：单行 JSON，包含 component / event 及传入键值对，便于日志聚合与检索。
    敏感或过长字段应在调用方截断后再传入。
    """
    payload = {"event": event, **kwargs}
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        line = json.dumps({"event": event, "log_error": "serialization_failed"})
    log_fn = getattr(logger, level, logger.info)
    log_fn(
        line,
        extra={
            "component": component,
            "trace_id": kwargs.get("trace_id"),
            "request_id": kwargs.get("request_id"),
        },
    )
