from __future__ import annotations

from typing import Dict


_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "http_400": {
        "en": "bad request",
        "zh": "请求不合法",
    },
    "invalid_payload": {
        "en": "payload validation failed",
        "zh": "请求参数校验失败",
    },
    "internal_server_error": {
        "en": "Internal server error",
        "zh": "服务器内部错误",
    },
    "workflow_not_found": {
        "en": "workflow not found",
        "zh": "工作流不存在",
    },
    "workflow_access_denied": {
        "en": "workflow access denied",
        "zh": "无权访问该工作流",
    },
    "workflow_execution_not_found": {
        "en": "workflow execution not found",
        "zh": "工作流执行记录不存在",
    },
    "chat_async_stream_not_supported": {
        "en": "async mode does not support stream=true",
        "zh": "异步模式暂不支持 stream=true",
    },
    "chat_async_job_not_found": {
        "en": "request not found or expired",
        "zh": "请求不存在或已过期",
    },
    "stream_not_found": {
        "en": "stream not found or expired",
        "zh": "流不存在或已过期",
    },
    "stream_resume_disabled": {
        "en": "stream resume is disabled",
        "zh": "断点续传未开启",
    },
    "knowledge_upload_filename_required": {
        "en": "Filename is required",
        "zh": "文件名不能为空",
    },
    "mcp_server_not_found": {
        "en": "MCP server not found",
        "zh": "MCP 服务不存在",
    },
    "skill_create_failed": {
        "en": "Failed to create skill",
        "zh": "创建技能失败",
    },
    "skill_update_failed": {
        "en": "Failed to update skill",
        "zh": "更新技能失败",
    },
    "skill_not_found": {
        "en": "skill not found",
        "zh": "技能不存在",
    },
    "skill_builtin_immutable": {
        "en": "built-in skill cannot be modified",
        "zh": "内置技能不可修改",
    },
    "skill_execution_blocked": {
        "en": "skill execution is blocked",
        "zh": "技能执行被阻止",
    },
    "knowledge_base_not_found": {
        "en": "knowledge base not found",
        "zh": "知识库不存在",
    },
    "knowledge_document_not_found": {
        "en": "knowledge document not found",
        "zh": "知识库文档不存在",
    },
    "knowledge_document_wrong_kb": {
        "en": "document does not belong to this knowledge base",
        "zh": "文档不属于当前知识库",
    },
    "knowledge_upload_unsupported_type": {
        "en": "unsupported file type",
        "zh": "不支持的文件类型",
    },
    "knowledge_upload_file_too_large": {
        "en": "file exceeds size limit",
        "zh": "文件超过大小限制",
    },
    "knowledge_embedding_model_not_found": {
        "en": "embedding model not found",
        "zh": "嵌入模型不存在",
    },
    "knowledge_search_embedding_dimension_mismatch": {
        "en": "embedding dimension mismatch",
        "zh": "嵌入维度不匹配",
    },
    "workflow_conflict": {
        "en": "workflow already exists",
        "zh": "工作流已存在",
    },
    "workflow_version_not_found": {
        "en": "workflow version not found",
        "zh": "工作流版本不存在",
    },
    "workflow_invalid_request": {
        "en": "invalid workflow request",
        "zh": "工作流请求不合法",
    },
    "mcp_invalid_server": {
        "en": "invalid MCP server",
        "zh": "无效的 MCP 服务",
    },
    "mcp_server_disabled": {
        "en": "MCP server is disabled",
        "zh": "MCP 服务已禁用",
    },
    "mcp_bad_request": {
        "en": "invalid MCP request",
        "zh": "MCP 请求不合法",
    },
}


def _resolve_locale(accept_language: str | None) -> str:
    if not accept_language:
        return "en"
    normalized = accept_language.lower()
    if normalized.startswith("zh") or ",zh" in normalized:
        return "zh"
    return "en"


def localize_error_message(*, code: str, default_message: str, accept_language: str | None) -> str:
    locale = _resolve_locale(accept_language)
    table = _ERROR_MESSAGES.get(code)
    if not table:
        return default_message
    return table.get(locale, default_message)

