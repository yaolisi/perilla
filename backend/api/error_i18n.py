from __future__ import annotations

from typing import Dict


# Grouped by API domain for maintainability; merged into _ERROR_MESSAGES below.
COMMON_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "http_400": {
        "en": "bad request",
        "zh": "请求不合法",
    },
    "idempotency_conflict": {
        "en": "idempotency conflict",
        "zh": "幂等冲突",
    },
    "idempotency_in_progress": {
        "en": "idempotency request is in progress",
        "zh": "幂等请求处理中",
    },
    "internal_server_error": {
        "en": "Internal server error",
        "zh": "服务器内部错误",
    },
    "invalid_payload": {
        "en": "payload validation failed",
        "zh": "请求参数校验失败",
    },
}

WORKFLOW_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "workflow_access_denied": {
        "en": "workflow access denied",
        "zh": "无权访问该工作流",
    },
    "workflow_admin_required": {
        "en": "workflow admin permission required",
        "zh": "需要工作流管理员权限",
    },
    "workflow_approval_task_expired": {
        "en": "workflow approval task expired",
        "zh": "工作流审批任务已过期",
    },
    "workflow_approval_task_not_found": {
        "en": "workflow approval task not found",
        "zh": "工作流审批任务不存在",
    },
    "workflow_cancel_invalid_request": {
        "en": "invalid workflow cancel request",
        "zh": "取消工作流请求不合法",
    },
    "workflow_conflict": {
        "en": "workflow already exists",
        "zh": "工作流已存在",
    },
    "workflow_diff_from_version_not_found": {
        "en": "source workflow version for diff not found",
        "zh": "用于比对的源工作流版本不存在",
    },
    "workflow_diff_to_version_not_found": {
        "en": "target workflow version for diff not found",
        "zh": "用于比对的目标工作流版本不存在",
    },
    "workflow_execution_delete_conflict": {
        "en": "workflow execution cannot be deleted in current state",
        "zh": "当前状态下无法删除工作流执行记录",
    },
    "workflow_execution_invalid_request": {
        "en": "invalid workflow execution request",
        "zh": "工作流执行请求不合法",
    },
    "workflow_execution_not_found": {
        "en": "workflow execution not found",
        "zh": "工作流执行记录不存在",
    },
    "workflow_governance_invalid_backpressure_strategy": {
        "en": "invalid workflow governance backpressure strategy",
        "zh": "工作流治理背压策略不合法",
    },
    "workflow_id_mismatch": {
        "en": "workflow id mismatch",
        "zh": "工作流 ID 不匹配",
    },
    "workflow_invalid_end_time": {
        "en": "invalid workflow end time",
        "zh": "工作流结束时间不合法",
    },
    "workflow_invalid_request": {
        "en": "invalid workflow request",
        "zh": "工作流请求不合法",
    },
    "workflow_invalid_start_time": {
        "en": "invalid workflow start time",
        "zh": "工作流开始时间不合法",
    },
    "workflow_invalid_time_range": {
        "en": "invalid workflow time range",
        "zh": "工作流时间范围不合法",
    },
    "workflow_namespace_tenant_mismatch": {
        "en": "workflow namespace tenant mismatch",
        "zh": "工作流命名空间租户不匹配",
    },
    "workflow_not_found": {
        "en": "workflow not found",
        "zh": "工作流不存在",
    },
    "workflow_runtime_error": {
        "en": "workflow runtime error",
        "zh": "工作流运行时错误",
    },
    "workflow_version_invalid_request": {
        "en": "invalid workflow version request",
        "zh": "工作流版本请求不合法",
    },
    "workflow_version_not_found": {
        "en": "workflow version not found",
        "zh": "工作流版本不存在",
    },
    "workflow_version_publish_invalid": {
        "en": "invalid workflow version publish request",
        "zh": "工作流版本发布请求不合法",
    },
    "workflow_version_rollback_publish_failed": {
        "en": "failed to publish rollback workflow version",
        "zh": "发布回滚工作流版本失败",
    },
}

CHAT_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "chat_async_job_not_found": {
        "en": "request not found or expired",
        "zh": "请求不存在或已过期",
    },
    "chat_async_stream_not_supported": {
        "en": "async mode does not support stream=true",
        "zh": "异步模式暂不支持 stream=true",
    },
    "chat_completion_failed": {
        "en": "chat completion failed",
        "zh": "对话补全失败",
    },
    "chat_messages_required": {
        "en": "messages are required",
        "zh": "messages 参数为必填项",
    },
    "stream_not_found": {
        "en": "stream not found or expired",
        "zh": "流不存在或已过期",
    },
    "stream_resume_disabled": {
        "en": "stream resume is disabled",
        "zh": "断点续传未开启",
    },
}

KNOWLEDGE_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "knowledge_access_denied": {
        "en": "knowledge access denied",
        "zh": "无权访问知识资源",
    },
    "knowledge_base_not_found": {
        "en": "knowledge base not found",
        "zh": "知识库不存在",
    },
    "knowledge_base_update_failed": {
        "en": "failed to update knowledge base",
        "zh": "更新知识库失败",
    },
    "knowledge_document_file_missing": {
        "en": "knowledge document file is missing",
        "zh": "知识库文档文件不存在",
    },
    "knowledge_document_no_file_path": {
        "en": "knowledge document has no file path",
        "zh": "知识库文档缺少文件路径",
    },
    "knowledge_document_not_found": {
        "en": "knowledge document not found",
        "zh": "知识库文档不存在",
    },
    "knowledge_document_wrong_kb": {
        "en": "document does not belong to this knowledge base",
        "zh": "文档不属于当前知识库",
    },
    "knowledge_embedding_model_not_found": {
        "en": "embedding model not found",
        "zh": "嵌入模型不存在",
    },
    "knowledge_internal_error": {
        "en": "knowledge internal error",
        "zh": "知识库内部错误",
    },
    "knowledge_resource_not_found": {
        "en": "knowledge resource not found",
        "zh": "知识资源不存在",
    },
    "knowledge_search_embedding_dimension_mismatch": {
        "en": "embedding dimension mismatch",
        "zh": "嵌入维度不匹配",
    },
    "knowledge_search_embedding_failed": {
        "en": "knowledge search embedding failed",
        "zh": "知识检索向量化失败",
    },
    "knowledge_upload_file_too_large": {
        "en": "file exceeds size limit",
        "zh": "文件超过大小限制",
    },
    "knowledge_upload_filename_required": {
        "en": "Filename is required",
        "zh": "文件名不能为空",
    },
    "knowledge_upload_unsupported_type": {
        "en": "unsupported file type",
        "zh": "不支持的文件类型",
    },
}

MCP_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "mcp_bad_request": {
        "en": "invalid MCP request",
        "zh": "MCP 请求不合法",
    },
    "mcp_import_failed": {
        "en": "MCP import failed",
        "zh": "MCP 导入失败",
    },
    "mcp_import_invalid": {
        "en": "invalid MCP import request",
        "zh": "MCP 导入请求不合法",
    },
    "mcp_invalid_server": {
        "en": "invalid MCP server",
        "zh": "无效的 MCP 服务",
    },
    "mcp_probe_failed": {
        "en": "MCP probe failed",
        "zh": "MCP 探测失败",
    },
    "mcp_server_disabled": {
        "en": "MCP server is disabled",
        "zh": "MCP 服务已禁用",
    },
    "mcp_server_not_found": {
        "en": "MCP server not found",
        "zh": "MCP 服务不存在",
    },
    "mcp_skill_preview_failed": {
        "en": "MCP skill preview failed",
        "zh": "MCP 技能预览失败",
    },
    "mcp_tools_list_failed": {
        "en": "failed to list MCP tools",
        "zh": "获取 MCP 工具列表失败",
    },
}

SKILL_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "skill_builtin_immutable": {
        "en": "built-in skill cannot be modified",
        "zh": "内置技能不可修改",
    },
    "skill_create_failed": {
        "en": "Failed to create skill",
        "zh": "创建技能失败",
    },
    "skill_execution_blocked": {
        "en": "skill execution is blocked",
        "zh": "技能执行被阻止",
    },
    "skill_not_found": {
        "en": "skill not found",
        "zh": "技能不存在",
    },
    "skill_update_failed": {
        "en": "Failed to update skill",
        "zh": "更新技能失败",
    },
}

AGENT_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "agent_create_failed": {
        "en": "Failed to create agent",
        "zh": "创建智能体失败",
    },
    "agent_invalid_execution_strategy": {
        "en": "invalid execution strategy",
        "zh": "执行策略不合法",
    },
    "agent_invalid_integer_field": {
        "en": "invalid integer field",
        "zh": "整数字段不合法",
    },
    "agent_invalid_messages_format": {
        "en": "invalid messages format",
        "zh": "消息格式不合法",
    },
    "agent_invalid_messages_json": {
        "en": "invalid messages json",
        "zh": "消息 JSON 格式不合法",
    },
    "agent_invalid_on_failure_strategy": {
        "en": "invalid on-failure strategy",
        "zh": "失败处理策略不合法",
    },
    "agent_invalid_replan_prompt": {
        "en": "invalid replan prompt",
        "zh": "重规划提示词不合法",
    },
    "agent_invalid_response_mode": {
        "en": "invalid response mode",
        "zh": "响应模式不合法",
    },
    "agent_invalid_tool_failure_reflection": {
        "en": "invalid tool failure reflection config",
        "zh": "工具失败反思配置不合法",
    },
    "agent_invalid_workspace_path": {
        "en": "invalid workspace path",
        "zh": "工作区路径不合法",
    },
    "agent_kb_store_unavailable": {
        "en": "knowledge base store is unavailable",
        "zh": "知识库存储不可用",
    },
    "agent_kernel_opts_execution_strategy_conflict": {
        "en": "kernel options conflict with execution strategy",
        "zh": "内核参数与执行策略冲突",
    },
    "agent_kernel_opts_max_parallel_conflict": {
        "en": "kernel options conflict with max parallel",
        "zh": "内核参数与最大并行度冲突",
    },
    "agent_knowledge_base_not_found": {
        "en": "agent knowledge base not found",
        "zh": "智能体知识库不存在",
    },
    "agent_model_not_found": {
        "en": "agent model not found",
        "zh": "智能体模型不存在",
    },
    "agent_nl_description_too_short": {
        "en": "natural language description is too short",
        "zh": "自然语言描述过短",
    },
    "agent_nl_generate_invalid": {
        "en": "invalid natural language generation request",
        "zh": "自然语言生成请求不合法",
    },
    "agent_nl_no_models": {
        "en": "no available models for natural language generation",
        "zh": "无可用模型用于自然语言生成",
    },
    "agent_not_found": {
        "en": "agent not found",
        "zh": "智能体不存在",
    },
    "agent_parallel_nodes_out_of_range": {
        "en": "parallel nodes value is out of range",
        "zh": "并行节点数超出范围",
    },
    "agent_replan_prompt_required": {
        "en": "replan prompt is required",
        "zh": "重规划提示词为必填项",
    },
    "agent_session_file_not_found": {
        "en": "agent session file not found",
        "zh": "智能体会话文件不存在",
    },
    "agent_session_message_not_found": {
        "en": "agent session message not found",
        "zh": "智能体会话消息不存在",
    },
    "agent_session_not_found": {
        "en": "agent session not found",
        "zh": "智能体会话不存在",
    },
    "agent_session_not_found_after_delete": {
        "en": "agent session not found after delete",
        "zh": "删除后未找到智能体会话",
    },
    "agent_session_save_failed": {
        "en": "failed to save agent session",
        "zh": "保存智能体会话失败",
    },
    "agent_skill_blocked_by_policy": {
        "en": "agent skill is blocked by policy",
        "zh": "智能体技能被策略阻止",
    },
    "agent_skill_not_found": {
        "en": "agent skill not found",
        "zh": "智能体技能不存在",
    },
    "agent_update_failed": {
        "en": "Failed to update agent",
        "zh": "更新智能体失败",
    },
    "agent_upload_file_too_large": {
        "en": "uploaded file is too large",
        "zh": "上传文件过大",
    },
    "agent_upload_rate_limited": {
        "en": "agent upload is rate limited",
        "zh": "智能体上传触发限流",
    },
    "agent_upload_too_many_files": {
        "en": "too many uploaded files",
        "zh": "上传文件数量过多",
    },
    "agent_upload_total_too_large": {
        "en": "total upload size is too large",
        "zh": "上传总大小过大",
    },
    "agent_workspace_not_found": {
        "en": "agent workspace not found",
        "zh": "智能体工作区不存在",
    },
}

TOOL_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "tool_not_found": {
        "en": "tool not found",
        "zh": "工具不存在",
    },
    "tool_registry_invalid": {
        "en": "tool registry invalid",
        "zh": "工具注册表无效",
    },
    "tool_web_search_invalid": {
        "en": "invalid web search request",
        "zh": "Web 搜索请求不合法",
    },
    "tool_web_search_not_registered": {
        "en": "web search tool is not registered",
        "zh": "Web 搜索工具未注册",
    },
}

EVENTS_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "events_internal_error": {
        "en": "events internal error",
        "zh": "事件服务内部错误",
    },
    "events_replay_not_found": {
        "en": "replay not found",
        "zh": "重放任务不存在",
    },
}

RAG_TRACE_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "rag_trace_finalize_invalid": {
        "en": "invalid rag trace finalize request",
        "zh": "RAG Trace 完成请求不合法",
    },
    "rag_trace_internal_error": {
        "en": "rag trace internal error",
        "zh": "RAG Trace 内部错误",
    },
    "rag_trace_invalid_chunks": {
        "en": "invalid rag trace chunks",
        "zh": "RAG Trace 分片数据不合法",
    },
}

ASR_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "asr_empty_audio": {
        "en": "audio content is empty",
        "zh": "音频内容为空",
    },
    "asr_model_not_asr": {
        "en": "model is not an ASR model",
        "zh": "模型不是 ASR 模型",
    },
    "asr_model_not_found": {
        "en": "ASR model not found",
        "zh": "ASR 模型不存在",
    },
    "asr_transcribe_failed": {
        "en": "ASR transcription failed",
        "zh": "ASR 转写失败",
    },
}

VLM_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "vlm_empty_image": {
        "en": "image content is empty",
        "zh": "图像内容为空",
    },
    "vlm_inference_failed": {
        "en": "VLM inference failed",
        "zh": "VLM 推理失败",
    },
    "vlm_invalid_image": {
        "en": "invalid image input",
        "zh": "图像输入不合法",
    },
    "vlm_invalid_request_json": {
        "en": "invalid VLM request json",
        "zh": "VLM 请求 JSON 不合法",
    },
    "vlm_model_not_vlm": {
        "en": "model is not a VLM model",
        "zh": "模型不是 VLM 模型",
    },
    "vlm_model_resolve_failed": {
        "en": "failed to resolve VLM model",
        "zh": "解析 VLM 模型失败",
    },
    "vlm_runtime_init_failed": {
        "en": "failed to initialize VLM runtime",
        "zh": "初始化 VLM 运行时失败",
    },
}

COLLABORATION_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "collaboration_correlation_mismatch": {
        "en": "collaboration correlation mismatch",
        "zh": "协作关联 ID 不匹配",
    },
    "collaboration_message_persist_failed": {
        "en": "failed to persist collaboration message",
        "zh": "保存协作消息失败",
    },
    "collaboration_session_not_found": {
        "en": "collaboration session not found",
        "zh": "协作会话不存在",
    },
}

MEMORY_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "memory_not_found": {
        "en": "memory not found",
        "zh": "记忆不存在",
    },
}

MISC_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
}

_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    **COMMON_ERROR_MESSAGES,
    **WORKFLOW_ERROR_MESSAGES,
    **CHAT_ERROR_MESSAGES,
    **KNOWLEDGE_ERROR_MESSAGES,
    **MCP_ERROR_MESSAGES,
    **SKILL_ERROR_MESSAGES,
    **AGENT_ERROR_MESSAGES,
    **TOOL_ERROR_MESSAGES,
    **EVENTS_ERROR_MESSAGES,
    **RAG_TRACE_ERROR_MESSAGES,
    **ASR_ERROR_MESSAGES,
    **VLM_ERROR_MESSAGES,
    **COLLABORATION_ERROR_MESSAGES,
    **MEMORY_ERROR_MESSAGES,
    **MISC_ERROR_MESSAGES,
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
