from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Self, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 消息角色（含 tool：用于 tool/skill 输出，表示环境观察而非用户意图）
Role = Literal["system", "user", "assistant", "tool"]
# 流式输出编码（SSE data 行负载格式；默认 openai 为兼容 OpenAI chat.completion.chunk）
StreamFormat = Literal["openai", "jsonl", "markdown"]


class ChatCompletionMetadataJsonMap(BaseModel):
    """chat 请求/响应侧透传元数据（路由分桶、resolved_model 等）。"""

    model_config = ConfigDict(extra="allow")


class ChatCompletionMessageContentItem(BaseModel):
    """chat.completion choice.message.content 数组元素（OpenAI 多模态片段；未知 type 保留扩展键）。"""

    model_config = ConfigDict(extra="allow")
    type: str = ""


class ChatCompletionChoiceMessage(BaseModel):
    """chat.completion 单条 choice.message（OpenAI 兼容，允许 tool_calls 等扩展字段）。"""

    model_config = ConfigDict(extra="allow")
    role: str = "assistant"
    content: Union[str, List[ChatCompletionMessageContentItem], None] = None


class ChatCompletionChoice(BaseModel):
    """chat.completion 单条 choice。"""

    model_config = ConfigDict(extra="allow")
    index: int = 0
    message: ChatCompletionChoiceMessage
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
    """token 用量（OpenAI 兼容，可扩展 completion_tokens_details 等）。"""

    model_config = ConfigDict(extra="allow")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class MessageImageUrlPayload(BaseModel):
    """OpenAI 风格 image_url 对象（url、detail 等）。"""

    model_config = ConfigDict(extra="allow")
    url: Optional[str] = None
    detail: Optional[str] = None


def image_url_part_url(payload: Union[MessageImageUrlPayload, Dict[str, Any], None]) -> str:
    """从 image_url 片段解析 url 字符串（兼容 dict / 模型）。"""
    if payload is None:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("url") or "")
    return str(payload.model_dump(mode="python").get("url") or "")


class MessageContentItem(BaseModel):
    """消息内容项（用于多模态消息）"""
    type: Literal["text", "image_url"]
    text: Optional[str] = None
    image_url: Optional[MessageImageUrlPayload] = None
    
    @model_validator(mode='after')
    def validate_content_item(self) -> Self:
        if self.type == "text" and not self.text:
            raise ValueError("Text content item must have 'text' field")
        if self.type == "image_url":
            if self.image_url is None:
                raise ValueError("Image URL content item must have 'image_url' field")
            if not image_url_part_url(self.image_url).strip():
                raise ValueError("Image URL content item must have 'image_url' field")
        return self


class Message(BaseModel):
    """聊天消息"""
    role: Role
    content: Union[str, List[MessageContentItem]]


class RAGConfig(BaseModel):
    """RAG 配置"""
    knowledge_base_id: Optional[str] = Field(default=None, description="知识库 ID（单个）")
    knowledge_base_ids: Optional[List[str]] = Field(default=None, description="知识库 ID 列表（多个）")
    top_k: int = Field(default=5, ge=1, le=50, description="检索的 chunk 数量")
    retrieval_mode: Literal["vector", "hybrid"] = Field(
        default="hybrid",
        description="检索模式：vector=单阶段向量检索，hybrid=关键词+向量+重排序",
    )
    keyword_top_k: int = Field(default=20, ge=1, le=100, description="关键词阶段候选数量")
    vector_top_k: int = Field(default=20, ge=1, le=100, description="向量阶段候选数量")
    rerank_top_k: int = Field(default=10, ge=1, le=100, description="重排序后保留数量")
    min_relevance_score: float = Field(default=0.5, ge=0, le=1, description="重排序相关性阈值")
    version_id: Optional[str] = Field(default=None, description="可选：按知识库版本检索")
    version_label: Optional[str] = Field(default=None, description="可选：按版本标签检索（由后端解析为 version_id）")
    # 注意：这里的 score_threshold 实际是“distance 阈值”(max_distance)：distance <= threshold 才保留
    # embedding 默认做了 L2 normalize（单位向量），因此常见距离范围大致在 0~2
    score_threshold: Optional[float] = Field(default=1.2, ge=0, le=2, description="距离阈值（distance<=threshold 才返回；默认1.2，范围0-2）")
    max_context_tokens: int = Field(default=2000, ge=100, le=10000, description="RAG 上下文最大 token 数（用于截断）")
    multi_hop_enabled: bool = Field(default=False, description="运行时多跳检索：首轮不足时扩展查询再检索并合并")
    multi_hop_max_rounds: int = Field(default=3, ge=2, le=5, description="多跳检索最大轮数（含首轮）")
    multi_hop_min_chunks: int = Field(default=2, ge=0, le=50, description="合并后 chunk 数低于该值则继续下一轮；0 表示不按数量触发")
    multi_hop_min_best_relevance: float = Field(
        default=0.0, ge=0, le=1, description="最佳 relevance 低于该值则继续下一轮；0 表示不按分数触发"
    )
    multi_hop_relax_relevance: bool = Field(default=True, description="第二轮及以后温和放宽 min_relevance_score")
    multi_hop_feedback_chars: int = Field(default=320, ge=80, le=2000, description="相关性反馈拼接时从高分 chunk 抽取的最大总字符数")

    @model_validator(mode='after')
    def validate_knowledge_base(self) -> Self:
        """验证至少提供一个知识库 ID"""
        if not self.knowledge_base_id and not self.knowledge_base_ids:
            raise ValueError("Either knowledge_base_id or knowledge_base_ids must be provided")
        return self


class ChatCompletionRequest(BaseModel):
    """统一的聊天完成请求"""
    model: Optional[str] = Field(default=None, description="模型 ID (精确匹配优先级最高)")
    model_require: Optional[str] = Field(default=None, description="模型要求/能力 (如 'vision', 'fast')")
    
    messages: List[Message] = Field(..., description="消息列表")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度参数")
    top_p: float = Field(default=1.0, ge=0, le=1, description="Top-P 参数")
    max_tokens: int = Field(default=2048, ge=1, le=8192, description="最大生成 token 数（默认 2048，上限 8192）")
    stream: bool = Field(default=False, description="是否流式响应")
    
    # 高级控制参数
    system_prompt: Optional[str] = Field(default=None, description="覆盖默认的系统提示词")
    max_history_messages: Optional[int] = Field(default=None, description="覆盖默认的历史消息条数")
    
    # RAG 配置（可选）
    rag: Optional[RAGConfig] = Field(default=None, description="RAG 知识库检索配置")

    # 客户端可选透传（如 role / is_admin 供智能路由分桶；不参与 LLM 拼接）
    metadata: Optional[ChatCompletionMetadataJsonMap] = Field(
        default=None,
        description="请求侧元数据（路由分桶等），与 assistant 输出无关",
    )
    # 流式：SSE 负载格式（与 LLM 输出文本无关；非 openai 便于消费端解析）
    stream_format: Optional[StreamFormat] = Field(
        default=None,
        description="流式时 data 行 JSON 格式；默认 openai。jsonl=紧凑键；markdown=偏文档输出",
    )
    # 流式：GZip 压缩整段 body（注：GZip 中间件对 text/event-stream 不压缩，需显式开启）
    stream_gzip: bool = Field(
        default=False,
        description="流式响应用 gzip 压缩；弱网降带宽。断点续传时与服务端元数据需一致",
    )


class ChatCompletionResponse(BaseModel):
    """聊天完成响应"""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Optional[ChatCompletionUsage] = None
    metadata: Optional[ChatCompletionMetadataJsonMap] = Field(
        default=None,
        description="解析元数据，如 resolved_model、resolved_via（智能路由/注册表）",
    )


# =========================
# RAG Trace Models
# =========================

class RAGTraceChunk(BaseModel):
    """RAG Trace Chunk"""
    doc_id: Optional[str] = None
    doc_name: Optional[str] = None
    chunk_id: Optional[str] = None
    score: float
    content: str
    content_tokens: Optional[int] = None
    rank: int


class RAGTrace(BaseModel):
    """RAG Trace"""
    id: str
    session_id: str
    message_id: str
    rag_id: str
    rag_type: str
    query: str
    embedding_model: str
    vector_store: str
    top_k: int
    retrieved_count: int
    score_threshold: Optional[float] = None
    injected_token_count: Optional[int] = None
    finalized: bool = False
    created_at: str
    chunks: List[RAGTraceChunk] = Field(default_factory=list)


class RAGTraceResponse(BaseModel):
    """RAG Trace 响应（供前端使用）"""
    rag_used: bool
    trace: Optional[RAGTrace] = None
