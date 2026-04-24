"""
聊天完成 API 端点
使用统一的 ModelAgent 接口
"""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
import json
import re
import time
import uuid
from typing import Optional, Any, Callable, Union, AsyncIterator, Set, cast, Literal
from log import logger, log_structured
from pydantic import BaseModel, Field

from api.errors import raise_api_error
from api.stream_resume_store import get_stream_resume_store, iter_resume_chunks
from config.settings import settings
from core.types import ChatCompletionRequest, ChatCompletionResponse, Message as LLMMessage
from core.agents.router import get_router
from core.conversation.manager import ConversationManager, Message as ConvMessage
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.memory.memory_store import MemoryStore, MemoryStoreConfig
from core.memory.memory_injector import MemoryInjector, MemoryInjectorConfig
from core.memory.memory_extractor import MemoryExtractor, MemoryExtractorConfig
from core.system.runtime_settings import get_auto_unload_local_model_on_switch

router = APIRouter()


class ChatStreamResumeBody(BaseModel):
    stream_id: str = Field(..., min_length=8)
    chunk_index: int = Field(..., ge=0)


# 0. 确定统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)

# 1. 初始化历史存储（MVP）
_history_store = HistoryStore(
    HistoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
    )
)


def _resolve_memory_inject_mode(raw_mode: str) -> Literal["recent", "keyword", "vector"]:
    if raw_mode == "vector":
        return "vector"
    if raw_mode == "keyword":
        return "keyword"
    return "recent"


# 2. 初始化长期记忆组件（MVP）
memory_store = MemoryStore(
    MemoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
        default_confidence=settings.memory_default_confidence,
        merge_enabled=bool(settings.memory_merge_enabled),
        merge_similarity_threshold=settings.memory_merge_similarity_threshold,
        conflict_enabled=bool(settings.memory_conflict_enabled),
        conflict_similarity_threshold=settings.memory_conflict_similarity_threshold,
        key_schema_enforced=bool(settings.memory_key_schema_enforced),
        key_schema_allow_unlisted=bool(settings.memory_key_schema_allow_unlisted),
    )
)
_memory_injector = MemoryInjector(
    memory_store,
    MemoryInjectorConfig(
        mode=_resolve_memory_inject_mode(settings.memory_inject_mode),
        top_k=settings.memory_inject_top_k,
        half_life_days=settings.memory_decay_half_life_days,
        default_confidence=settings.memory_default_confidence,
    ),
)
_memory_extractor = MemoryExtractor(
    memory_store,
    MemoryExtractorConfig(
        enabled=bool(settings.memory_extractor_enabled),
        temperature=settings.memory_extractor_temperature,
        top_p=settings.memory_extractor_top_p,
        max_tokens=settings.memory_extractor_max_tokens,
    ),
)
_background_tasks: Set[asyncio.Task[Any]] = set()


def _schedule_memory_extraction(
    *,
    user_id: str,
    model_id: str,
    user_text: str,
    assistant_text: str,
    completion_id: str,
    stream: bool,
) -> None:
    task = asyncio.create_task(
        _memory_extractor.extract_and_store(
            user_id=user_id,
            model_id=model_id,
            user_text=user_text,
            assistant_text=assistant_text,
            meta={"completion_id": completion_id, "model": model_id, "stream": stream},
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

# 3. 初始化对话管理器（依赖 HistoryStore 和 MemoryInjector）
conv_manager = ConversationManager(
    history_store=_history_store,
    memory_injector=_memory_injector,
    max_messages=8
)


def _extract_text_from_items(items: list[Any]) -> str:
    parts: list[str] = []
    for item in items:
        if hasattr(item, "type") and item.type == "text" and getattr(item, "text", None):
            parts.append(str(item.text))
            continue
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
            parts.append(str(item["text"]))
    return " ".join(parts).strip()


def _last_user_content(messages: list[LLMMessage]) -> str:
    for m in reversed(messages):
        if m.role != "user":
            continue
        if isinstance(m.content, str):
            return (m.content or "").strip()
        if isinstance(m.content, list):
            return _extract_text_from_items(m.content)
        return ""
    return ""


_TRANSPORT_PREFIX_RE = re.compile(
    r"^\s*Sender\s*\(untrusted metadata\):\s*```json[\s\S]*?```\s*",
    re.IGNORECASE,
)
_LEADING_TIME_RE = re.compile(r"^\s*\[[^\]]+\]\s*")
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINKING_PREFIX_RE = re.compile(r"^\s*thinking process\s*:\s*", re.IGNORECASE)


def _strip_transport_wrappers(text: str) -> str:
    s = text or ""
    if bool(getattr(settings, "chat_input_strip_transport_wrappers", True)):
        s = _TRANSPORT_PREFIX_RE.sub("", s)
        s = _LEADING_TIME_RE.sub("", s)
    return s.strip()


def _sanitize_user_content(content: Any) -> Any:
    if not bool(getattr(settings, "chat_input_strip_transport_wrappers", True)):
        return content
    if isinstance(content, str):
        return _strip_transport_wrappers(content)
    if isinstance(content, list):
        cleaned = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                new_item = dict(item)
                new_item["text"] = _strip_transport_wrappers(item.get("text", ""))
                cleaned.append(new_item)
            else:
                cleaned.append(item)
        return cleaned
    return content


def _sanitize_assistant_output(text: str) -> str:
    if not bool(getattr(settings, "chat_output_strip_reasoning", True)):
        return text
    s = text or ""
    s = _THINK_BLOCK_RE.sub("", s)
    s = _THINKING_PREFIX_RE.sub("", s)
    if "</think>" in s:
        s = s.split("</think>", 1)[-1]
    return s.strip()

def _get_user_id(request: Request) -> str:
    """获取用户 ID（已统一到 core.utils.user_context）"""
    from core.utils.user_context import get_user_id
    return cast(str, get_user_id(request))


def _normalized_persistence_mode() -> str:
    mode = (getattr(settings, "chat_persistence_mode", "full") or "full").strip().lower()
    if mode not in {"off", "minimal", "full"}:
        return "full"
    return mode


def _clean_session_title(title_hint: str) -> str:
    text = (title_hint or "").strip().replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if not text or text.startswith("{") or text.startswith("["):
        return "New Chat"
    max_len = max(8, int(getattr(settings, "chat_session_title_max_len", 50) or 50))
    return text[:max_len]


def _get_idempotency_key(request: Request) -> Optional[str]:
    names = (getattr(settings, "chat_idempotency_headers", "") or "").split(",")
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        value = (request.headers.get(name) or "").strip()
        if value:
            return value[:128]
    return None


def _is_truthy_header(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _should_force_new_session(request: Request) -> bool:
    names = (getattr(settings, "chat_force_new_session_headers", "") or "").split(",")
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        value = request.headers.get(name)
        if value and _is_truthy_header(value):
            return True
    return False


def _extract_user_attachments(last_user_msg: Optional[LLMMessage]) -> Optional[list[dict]]:
    if not last_user_msg or not isinstance(last_user_msg.content, list):
        return None
    attachments: list[dict[str, Any]] = []
    for item in last_user_msg.content:
        if isinstance(item, dict) and item.get("type") == "image_url":
            url = item.get("image_url", {}).get("url", "")
            if url:
                attachments.append({"type": "image", "url": url})
    return attachments or None


def _get_or_create_session_id(
    *,
    request: Request,
    user_id: str,
    title_hint: str,
    model_id: str,
    allow_create: bool,
    force_new: bool = False,
) -> Optional[str]:
    if force_new:
        if not allow_create:
            return None
        title = _clean_session_title(title_hint)
        return cast(
            str,
            _history_store.create_session(user_id=user_id, title=title, last_model=model_id),
        )

    sid = (request.headers.get("X-Session-Id") or "").strip()
    if sid and _history_store.session_exists(user_id=user_id, session_id=sid):
        return sid
    # 无显式会话时可按时间窗复用最近会话，避免外部客户端每轮新建会话
    reuse_minutes = int(getattr(settings, "chat_session_reuse_window_minutes", 15) or 0)
    if reuse_minutes > 0:
        recent_sid = _history_store.get_recent_active_session_id(user_id=user_id, within_minutes=reuse_minutes)
        if isinstance(recent_sid, str) and recent_sid:
            return recent_sid
    if not allow_create:
        return None
    # 后端自动创建会话
    title = _clean_session_title(title_hint)
    return cast(
        str,
        _history_store.create_session(user_id=user_id, title=title, last_model=model_id),
    )


async def _maybe_unload_previous_model(*, user_id: str, session_id: str, current_model_id: str) -> None:
    try:
        session = _history_store.get_session(user_id=user_id, session_id=session_id)
        last_model = (session or {}).get("last_model")
        if not last_model or last_model == current_model_id:
            return
        from core.models.registry import get_model_registry
        from core.runtimes.factory import get_runtime_factory

        reg = get_model_registry()
        prev_desc = reg.get_model(last_model)
        if not prev_desc or getattr(prev_desc, "provider", None) != "local":
            return
        await get_runtime_factory().unload_model(prev_desc.id)
        logger.info("[Chat] Unloaded previous model %s before switching to %s", last_model, current_model_id)
    except Exception as e:
        logger.warning("[Chat] Failed to unload previous model: %s", e)


def _collect_messages_for_model_selection(req: ChatCompletionRequest, request: Request, user_id: str) -> Optional[list[dict]]:
    messages_dict = [msg.model_dump() for msg in req.messages] if req.messages else None
    if req.model != "auto" or not _history_store:
        return messages_dict

    try:
        sid: Optional[str] = (request.headers.get("X-Session-Id") or "").strip()
        if not sid or not _history_store.session_exists(user_id=user_id, session_id=sid):
            reuse_minutes = int(getattr(settings, "chat_session_reuse_window_minutes", 15) or 0)
            if reuse_minutes > 0:
                sid = _history_store.get_recent_active_session_id(user_id=user_id, within_minutes=reuse_minutes)

        if not sid:
            return messages_dict

        session_messages = _history_store.list_messages(user_id=user_id, session_id=sid, limit=10)
        all_messages = session_messages + (messages_dict or [])
        seen_ids = set()
        unique_messages = []
        for msg in all_messages:
            msg_id = msg.get("id", id(msg))
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            unique_messages.append(msg)
        logger.info(f"[Chat] Checking {len(unique_messages)} messages (including session history) for image detection")
        return unique_messages
    except Exception as e:
        logger.warning(f"[Chat] Failed to check session history for images: {e}")
        return messages_dict


def _debug_log_message_shapes(messages_dict: Optional[list[dict]]) -> None:
    if not messages_dict:
        return
    for i, msg in enumerate(messages_dict):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        logger.info(f"[Chat] Message {i} has multimodal content with {len(content)} items")
        for j, item in enumerate(content):
            if isinstance(item, dict):
                logger.info(f"[Chat]   Item {j}: type={item.get('type')}")


def _resolve_model_for_request(req: ChatCompletionRequest, request: Request, user_id: str) -> str:
    from core.models.selector import get_model_selector

    selector = get_model_selector()
    messages_dict = _collect_messages_for_model_selection(req, request, user_id)
    _debug_log_message_shapes(messages_dict)
    descriptor = selector.resolve(model_id=req.model, model_require=req.model_require, messages=messages_dict)
    actual_model_id = descriptor.id
    req.model = actual_model_id
    return actual_model_id


def _collect_kb_infos(req: ChatCompletionRequest, temp_kb_store: Any) -> dict[str, dict]:
    kb_ids: list[str] = []
    if req.rag and req.rag.knowledge_base_ids:
        kb_ids.extend(req.rag.knowledge_base_ids)
    if req.rag and req.rag.knowledge_base_id and req.rag.knowledge_base_id not in kb_ids:
        kb_ids.append(req.rag.knowledge_base_id)
    if not kb_ids:
        raise ValueError("No knowledge_base_id or knowledge_base_ids provided")

    kb_infos: dict[str, dict] = {}
    for kb_id in kb_ids:
        kb_info = temp_kb_store.get_knowledge_base(kb_id)
        if not kb_info:
            logger.warning(f"[RAG] Knowledge base '{kb_id}' not found, skipping")
            continue
        kb_infos[kb_id] = kb_info
    if not kb_infos:
        raise ValueError("No valid knowledge bases found")
    return kb_infos


def _build_kb_store(model_registry: Any, kb_infos: dict[str, dict]) -> Any:
    def _resolve_embedding_dim() -> int:
        first_kb_id = list(kb_infos.keys())[0]
        embedding_model_id = kb_infos[first_kb_id]["embedding_model_id"]
        embedding_model = model_registry.get_model(embedding_model_id)
        if not embedding_model:
            logger.warning(
                f"[RAG] Embedding model '{embedding_model_id}' not found, "
                f"falling back to system default dimension {settings.memory_embedding_dim}"
            )
            return int(settings.memory_embedding_dim)
        actual_dim = embedding_model.metadata.get("embedding_dim", settings.memory_embedding_dim)
        logger.info(
            f"[RAG] Using embedding_dim={actual_dim} from model '{embedding_model_id}' "
            f"for knowledge bases {list(kb_infos.keys())}"
        )
        return int(actual_dim)

    from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig

    actual_embedding_dim = _resolve_embedding_dim()
    kb_store = KnowledgeBaseStore(
        KnowledgeBaseConfig(db_path=_db_path, embedding_dim=actual_embedding_dim)
    )
    for kb_id, kb_info in kb_infos.items():
        kb_embedding_model_id = kb_info["embedding_model_id"]
        kb_embedding_model = model_registry.get_model(kb_embedding_model_id)
        if kb_embedding_model:
            kb_dim = kb_embedding_model.metadata.get("embedding_dim", actual_embedding_dim)
            kb_store._ensure_vec_table_dimension(kb_id, kb_dim)
    return kb_store


async def _execute_rag_plugin(req: ChatCompletionRequest, plugin_context: Any) -> dict[str, Any]:
    from core.plugins.executor import get_plugin_executor

    plugin_executor = get_plugin_executor()
    assert req.rag is not None
    rag_result = await plugin_executor.execute(
        name="rag",
        input_data={"messages": [m.model_dump() for m in req.messages], "rag": req.rag.model_dump()},
        context=plugin_context,
    )
    return rag_result if isinstance(rag_result, dict) else {}


def _build_rag_plugin_context(
    *,
    session_id: Optional[str],
    user_id: str,
    message_id: str,
    model_registry: Any,
    kb_store: Any,
) -> Any:
    from core.plugins.context import PluginContext
    from core.runtimes.factory import get_runtime_factory
    from core.plugins.registry import get_plugin_registry

    return PluginContext(
        session_id=session_id,
        user_id=user_id,
        message_id=message_id,
        logger=logger,
        memory=memory_store,
        registry=model_registry,
        knowledge_base_store=kb_store,
        runtime_factory=get_runtime_factory(),
        plugin_registry=get_plugin_registry(),
    )


async def _apply_rag_plugin_if_needed(
    req: ChatCompletionRequest,
    *,
    session_id: Optional[str],
    user_id: str,
    message_id: str,
) -> tuple[Optional[str], int]:
    if not req.rag:
        return None, 0
    try:
        from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig
        from core.models.registry import get_model_registry

        model_registry = get_model_registry()
        temp_kb_store = KnowledgeBaseStore(
            KnowledgeBaseConfig(db_path=_db_path, embedding_dim=settings.memory_embedding_dim)
        )
        kb_infos = _collect_kb_infos(req, temp_kb_store)
        kb_store = _build_kb_store(model_registry, kb_infos)
        plugin_context = _build_rag_plugin_context(
            session_id=session_id,
            user_id=user_id,
            message_id=message_id,
            model_registry=model_registry,
            kb_store=kb_store,
        )
        rag_result = await _execute_rag_plugin(req, plugin_context)
        if "messages" in rag_result:
            req.messages = [LLMMessage(**m) for m in rag_result["messages"]]
            logger.info(f"RAG Plugin enhanced messages: {len(req.messages)} messages after RAG")

        metadata = rag_result.get("metadata", {}) if isinstance(rag_result, dict) else {}
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        retrieved_count = metadata.get("retrieved_chunks", 0) if isinstance(metadata, dict) else 0
        return cast(Optional[str], trace_id), int(retrieved_count or 0)
    except Exception as e:
        logger.error(f"RAG Plugin execution failed: {e}", exc_info=True)
        return None, 0


def _prepare_chat_request_state(
    req: ChatCompletionRequest,
    request: Request,
    actual_model_id: str,
    user_id: str,
) -> tuple[str, Optional[str], str, Optional[LLMMessage], bool, Optional[str], bool]:
    if not req.messages:
        raise_api_error(
            status_code=400,
            code="chat_messages_required",
            message="messages 不能为空",
        )

    logger.info("Received messages structure:")
    for i, msg in enumerate(req.messages):
        content_type = type(msg.content).__name__
        if isinstance(msg.content, list):
            logger.info(f"  Message {i} ({msg.role}): content is list with {len(msg.content)} items")
            for j, item in enumerate(msg.content):
                if isinstance(item, dict):
                    logger.info(f"    Item {j}: type={item.get('type')}, keys={list(item.keys())}")
                else:
                    logger.info(f"    Item {j}: type={type(item).__name__}")
        else:
            logger.info(f"  Message {i} ({msg.role}): content is {content_type}: {msg.content[:100]}...")

    user_text = _strip_transport_wrappers(_last_user_content(req.messages))
    persistence_mode = _normalized_persistence_mode()
    request_id = _get_idempotency_key(request)
    force_new_session = _should_force_new_session(request)

    last_user_msg = next((msg for msg in reversed(req.messages) if msg.role == "user"), None)
    should_create_session = persistence_mode != "off" and bool(user_text)
    session_id = _get_or_create_session_id(
        request=request,
        user_id=user_id,
        title_hint=user_text,
        model_id=actual_model_id,
        allow_create=should_create_session,
        force_new=force_new_session,
    )
    return (
        user_text,
        session_id,
        persistence_mode,
        last_user_msg,
        should_create_session,
        request_id,
        force_new_session,
    )


def _finalize_rag_trace_for_message(trace_id: Optional[str], message: Optional[Any], response_text: str) -> None:
    if not trace_id or not message:
        return
    injected_token_count = len(response_text) // 4
    try:
        from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig

        trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
        trace_store.finalize_trace(trace_id, injected_token_count, final_message_id=message.id)
        logger.debug(f"[RAGTrace] Finalized trace {trace_id} for message {message.id}")
    except Exception as e:
        logger.warning(f"[RAGTrace] Failed to finalize trace {trace_id}: {e}")


def _handle_streaming_chat(
    *,
    req: ChatCompletionRequest,
    request: Request,
    agent: Any,
    session_id: Optional[str],
    completion_id: str,
    created_time: int,
    trace_id: Optional[str],
    user_text: str,
    user_id: str,
    persistence_mode: str,
    request_id: Optional[str],
    conv_manager: ConversationManager,
    persist_success_turn: Callable[[str, bool], Optional[Any]],
) -> StreamingResponse:
    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if session_id:
        stream_headers["X-Session-Id"] = session_id
    return StreamingResponse(
        _stream_event_generator(
            req=req,
            request=request,
            agent=agent,
            session_id=session_id,
            completion_id=completion_id,
            created_time=created_time,
            trace_id=trace_id,
            user_text=user_text,
            user_id=user_id,
            persistence_mode=persistence_mode,
            request_id=request_id,
            conv_manager=conv_manager,
            persist_success_turn=persist_success_turn,
        ),
        media_type="text/event-stream",
        headers=stream_headers,
    )


def _stream_build_chunk(*, completion_id: str, created_time: int, model_id: str, content: str) -> str:
    chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model_id,
        "choices": [{"index": 0, "delta": {"content": content}}],
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def _stream_on_success(
    *,
    req: ChatCompletionRequest,
    request: Request,
    session_id: Optional[str],
    completion_id: str,
    trace_id: Optional[str],
    user_text: str,
    user_id: str,
    full_text: str,
    stream_start: float,
    persist_success_turn: Callable[[str, bool], Optional[Any]],
) -> None:
    model_id = cast(str, req.model)
    duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
    log_structured(
        "Chat",
        "chat_llm_done",
        model_id=model_id,
        session_id=session_id or "",
        stream=True,
        completion_id=completion_id,
        duration_ms=duration_ms,
        response_len=len(full_text),
        rag_used=bool(trace_id),
    )
    logger.info(f"Streaming completion finished for {completion_id}")
    try:
        final_text = _sanitize_assistant_output(full_text)
        if user_text and final_text:
            message = persist_success_turn(final_text, True)
            _finalize_rag_trace_for_message(trace_id, message, final_text)
            if not await request.is_disconnected():
                _schedule_memory_extraction(
                    user_id=user_id,
                    model_id=model_id,
                    user_text=user_text,
                    assistant_text=final_text,
                    completion_id=completion_id,
                    stream=True,
                )
            else:
                logger.info(f"Client disconnected for {completion_id}, skipping memory extraction")
    except Exception as e:
        logger.warning(f"[Chat] Failed to persist/finalize after stream: {e}")


def _stream_handle_client_disconnect(
    *,
    req: ChatCompletionRequest,
    session_id: Optional[str],
    completion_id: str,
    user_text: str,
    user_id: str,
    full_text: str,
    stream_start: float,
    persistence_mode: str,
    request_id: Optional[str],
    conv_manager: ConversationManager,
) -> None:
    model_id = cast(str, req.model)
    duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
    log_structured(
        "Chat",
        "chat_llm_done",
        model_id=model_id,
        session_id=session_id or "",
        stream=True,
        completion_id=completion_id,
        duration_ms=duration_ms,
        response_len=len(full_text),
        client_disconnected=True,
    )
    logger.info(f"Client disconnected during streaming for {completion_id}")
    if not (user_text and full_text and persistence_mode == "full" and session_id):
        return
    try:
        partial_text = _sanitize_assistant_output(full_text)
        if partial_text:
            conv_manager.append_assistant_message(
                user_id=user_id,
                session_id=session_id,
                content=partial_text,
                model_id=model_id,
                meta={
                    "completion_id": completion_id,
                    "stream": True,
                    "incomplete": True,
                    "error": "client_disconnected",
                },
                request_id=f"{request_id}:assistant:incomplete" if request_id else None,
            )
    except Exception as save_error:
        logger.warning(f"Failed to save incomplete message: {save_error}")


def _stream_on_exception(
    *,
    req: ChatCompletionRequest,
    session_id: Optional[str],
    completion_id: str,
    created_time: int,
    user_text: str,
    user_id: str,
    full_text: str,
    stream_start: float,
    persistence_mode: str,
    request_id: Optional[str],
    conv_manager: ConversationManager,
    err: Exception,
) -> list[str]:
    model_id = cast(str, req.model)
    is_client_disconnect = (
        "client disconnected" in str(err).lower()
        or "connection closed" in str(err).lower()
        or isinstance(err, (ConnectionError, BrokenPipeError))
    )
    if is_client_disconnect:
        _stream_handle_client_disconnect(
            req=req,
            session_id=session_id,
            completion_id=completion_id,
            user_text=user_text,
            user_id=user_id,
            full_text=full_text,
            stream_start=stream_start,
            persistence_mode=persistence_mode,
            request_id=request_id,
            conv_manager=conv_manager,
        )
        return []

    duration_ms = round((time.perf_counter() - stream_start) * 1000, 2)
    log_structured(
        "Chat",
        "chat_llm_failed",
        model_id=model_id,
        session_id=session_id,
        stream=True,
        completion_id=completion_id,
        error=str(err)[:200],
        duration_ms=duration_ms,
    )
    logger.error(f"Streaming error for {completion_id}: {str(err)}", exc_info=True)
    try:
        return [
            _stream_build_chunk(
                completion_id=completion_id,
                created_time=created_time,
                model_id=model_id,
                content=f"\nError: {str(err)}",
            ),
            "data: [DONE]\n\n",
        ]
    except Exception:
        return []


async def _stream_event_generator(
    *,
    req: ChatCompletionRequest,
    request: Request,
    agent: Any,
    session_id: Optional[str],
    completion_id: str,
    created_time: int,
    trace_id: Optional[str],
    user_text: str,
    user_id: str,
    persistence_mode: str,
    request_id: Optional[str],
    conv_manager: ConversationManager,
    persist_success_turn: Callable[[str, bool], Optional[Any]],
) -> AsyncIterator[str]:
    model_id = cast(str, req.model)
    full_text = ""
    stream_start = time.perf_counter()
    log_structured("Chat", "chat_llm_start", model_id=model_id, session_id=session_id, stream=True, completion_id=completion_id)
    logger.info(f"Starting event generator for {completion_id}")

    resume_enabled = bool(getattr(settings, "chat_stream_resume_enabled", True))
    stream_id: Optional[str] = None
    disconnected = False
    resume_store = get_stream_resume_store() if resume_enabled else None

    if resume_enabled and resume_store:
        stream_id = str(uuid.uuid4())
        rsess = resume_store.create(stream_id, user_id)
        rsess.completion_id = completion_id
        rsess.model_id = model_id
        rsess.sse_created = int(created_time)
        meta = {"object": "openvitamin.stream.meta", "stream_id": stream_id, "completion_id": completion_id}
        meta_sse = f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"
        await resume_store.append_chunk(stream_id, meta_sse)
        yield meta_sse

    try:
        async for token in agent.stream_chat(req):
            if await request.is_disconnected():
                if resume_enabled:
                    disconnected = True
                else:
                    logger.info(f"Client disconnected for {completion_id}, stopping stream")
                    break
            full_text += token
            sse = _stream_build_chunk(
                completion_id=completion_id,
                created_time=created_time,
                model_id=model_id,
                content=token,
            )
            if resume_enabled and stream_id and resume_store:
                await resume_store.append_chunk(stream_id, sse)
            if not disconnected:
                yield sse

        await _stream_on_success(
            req=req,
            request=request,
            session_id=session_id,
            completion_id=completion_id,
            trace_id=trace_id,
            user_text=user_text,
            user_id=user_id,
            full_text=full_text,
            stream_start=stream_start,
            persist_success_turn=persist_success_turn,
        )
        done_sse = "data: [DONE]\n\n"
        if resume_enabled and stream_id and resume_store:
            await resume_store.append_chunk(stream_id, done_sse)
            await resume_store.finish(stream_id)
        if not disconnected:
            yield done_sse
    except Exception as e:
        for chunk in _stream_on_exception(
            req=req,
            session_id=session_id,
            completion_id=completion_id,
            created_time=created_time,
            user_text=user_text,
            user_id=user_id,
            full_text=full_text,
            stream_start=stream_start,
            persistence_mode=persistence_mode,
            request_id=request_id,
            conv_manager=conv_manager,
            err=e,
        ):
            if resume_enabled and stream_id and resume_store:
                await resume_store.append_chunk(stream_id, chunk)
            if not disconnected:
                yield chunk
        if resume_enabled and stream_id and resume_store:
            await resume_store.finish(stream_id)


async def _handle_nonstream_chat(
    *,
    req: ChatCompletionRequest,
    response: Response,
    agent: Any,
    session_id: Optional[str],
    completion_id: str,
    created_time: int,
    trace_id: Optional[str],
    user_text: str,
    user_id: str,
    persist_success_turn: Callable[[str, bool], Optional[Any]],
) -> ChatCompletionResponse:
    model_id = cast(str, req.model)
    log_structured("Chat", "chat_llm_start", model_id=model_id, session_id=session_id or "", stream=False, completion_id=completion_id)
    nonstream_start = time.perf_counter()
    try:
        content = _sanitize_assistant_output(await agent.chat(req))
        duration_ms = round((time.perf_counter() - nonstream_start) * 1000, 2)
        log_structured(
            "Chat",
            "chat_llm_done",
            model_id=model_id,
            session_id=session_id or "",
            stream=False,
            completion_id=completion_id,
            duration_ms=duration_ms,
            response_len=len(content) if content else 0,
            rag_used=bool(trace_id),
        )
        logger.info(f"Chat completion successful for {completion_id}")
    except Exception as e:
        duration_ms = round((time.perf_counter() - nonstream_start) * 1000, 2)
        log_structured(
            "Chat",
            "chat_llm_failed",
            model_id=model_id,
            session_id=session_id or "",
            stream=False,
            completion_id=completion_id,
            error=str(e)[:200],
            duration_ms=duration_ms,
        )
        logger.error(f"Chat completion error for {completion_id}: {str(e)}", exc_info=True)
        raise_api_error(status_code=500, code="chat_completion_failed", message=str(e))

    if user_text and content:
        message = persist_success_turn(content, False)
        _finalize_rag_trace_for_message(trace_id, message, content)
        _schedule_memory_extraction(
            user_id=user_id,
            model_id=model_id,
            user_text=user_text,
            assistant_text=content,
            completion_id=completion_id,
            stream=False,
        )

    if session_id:
        response.headers["X-Session-Id"] = session_id

    return ChatCompletionResponse(
        id=completion_id,
        created=created_time,
        model=model_id,
        choices=[
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        usage=None,
    )


async def _prepare_chat_runtime_context(
    *,
    req: ChatCompletionRequest,
    user_id: str,
    session_id: Optional[str],
    actual_model_id: str,
    user_text: str,
    persistence_mode: str,
    last_user_msg: Optional[LLMMessage],
    request_id: Optional[str],
    message_id: str,
) -> tuple[Optional[str], int]:
    await _prepare_chat_model_runtime(user_id=user_id, session_id=session_id, actual_model_id=actual_model_id)
    _persist_full_user_turn(
        user_id=user_id,
        session_id=session_id,
        persistence_mode=persistence_mode,
        user_text=user_text,
        last_user_msg=last_user_msg,
        request_id=request_id,
    )
    safe_messages_dict = _build_safe_messages_dict(req=req, user_id=user_id, session_id=session_id, persistence_mode=persistence_mode)
    req.messages = [LLMMessage(**m) for m in safe_messages_dict]

    return await _apply_rag_plugin_if_needed(
        req,
        session_id=session_id,
        user_id=user_id,
        message_id=message_id,
    )


async def _prepare_chat_model_runtime(*, user_id: str, session_id: Optional[str], actual_model_id: str) -> None:
    if session_id and get_auto_unload_local_model_on_switch():
        await _maybe_unload_previous_model(
            user_id=user_id,
            session_id=session_id,
            current_model_id=actual_model_id,
        )
    try:
        from core.runtimes.factory import get_runtime_factory

        await get_runtime_factory().auto_release_unused_local_runtimes(
            keep_model_ids={actual_model_id},
            reason="chat_api",
        )
    except Exception:
        pass


def _persist_full_user_turn(
    *,
    user_id: str,
    session_id: Optional[str],
    persistence_mode: str,
    user_text: str,
    last_user_msg: Optional[LLMMessage],
    request_id: Optional[str],
) -> None:
    if not (persistence_mode == "full" and user_text and session_id):
        return
    user_attachments = _extract_user_attachments(last_user_msg)
    conv_manager.append_user_message(
        user_id=user_id,
        session_id=session_id,
        content=_sanitize_user_content(last_user_msg.content if last_user_msg else user_text),
        meta={"attachments": user_attachments} if user_attachments else None,
        request_id=f"{request_id}:user" if request_id else None,
    )


def _build_safe_messages_dict(
    *,
    req: ChatCompletionRequest,
    user_id: str,
    session_id: Optional[str],
    persistence_mode: str,
) -> list[dict[str, Any]]:
    if persistence_mode == "full" and session_id:
        safe_messages_dict = conv_manager.build_llm_context(
            user_id=user_id,
            session_id=session_id,
            max_messages=req.max_history_messages,
            system_prompt=req.system_prompt,
        )
    else:
        safe_messages_dict = [m.model_dump() for m in req.messages]
        if req.system_prompt:
            safe_messages_dict = [m for m in safe_messages_dict if m.get("role") != "system"]
            safe_messages_dict.insert(0, {"role": "system", "content": req.system_prompt})
    for msg in safe_messages_dict:
        if msg.get("role") == "user":
            msg["content"] = _sanitize_user_content(msg.get("content"))
    logger.info(f"Context built: {len(safe_messages_dict)} messages prepared for {req.model}")
    return safe_messages_dict


def _build_user_message_meta(last_user_msg: Optional[LLMMessage]) -> Optional[dict[str, Any]]:
    attachments = _extract_user_attachments(last_user_msg)
    return {"attachments": attachments} if attachments else None


def _maybe_append_minimal_user_turn(
    *,
    should_append: bool,
    user_id: str,
    session_id: str,
    request_id: Optional[str],
    user_text: str,
    last_user_msg: Optional[LLMMessage],
) -> None:
    if not should_append:
        return
    conv_manager.append_user_message(
        user_id=user_id,
        session_id=session_id,
        content=_sanitize_user_content(last_user_msg.content if last_user_msg else user_text),
        meta=_build_user_message_meta(last_user_msg),
        request_id=f"{request_id}:user" if request_id else None,
    )


def _build_persist_success_turn(
    *,
    req: ChatCompletionRequest,
    session_id: Optional[str],
    user_text: str,
    persistence_mode: str,
    last_user_msg: Optional[LLMMessage],
    request_id: Optional[str],
    user_id: str,
    completion_id: str,
    trace_id: Optional[str],
    retrieved_count: int,
) -> Callable[[str, bool], Optional[Any]]:
    model_id = cast(str, req.model)

    def _persist_success_turn(assistant_text: str, is_stream: bool) -> Optional[Any]:
        if not session_id or not user_text or not assistant_text or persistence_mode == "off":
            return None
        _maybe_append_minimal_user_turn(
            should_append=persistence_mode == "minimal",
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
            user_text=user_text,
            last_user_msg=last_user_msg,
        )
        return conv_manager.append_assistant_message(
            user_id=user_id,
            session_id=session_id,
            content=assistant_text,
            model_id=model_id,
            meta={
                "completion_id": completion_id,
                "stream": is_stream,
                "rag": {"used": bool(trace_id), "trace_id": trace_id, "retrieved_count": retrieved_count if trace_id else 0},
                "params": {
                    "temperature": req.temperature,
                    "top_p": req.top_p,
                    "max_tokens": req.max_tokens,
                    "system_prompt": req.system_prompt,
                },
            },
            request_id=f"{request_id}:assistant" if request_id else None,
        )

    return _persist_success_turn

@router.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    response: Response,
) -> Union[ChatCompletionResponse, StreamingResponse]:
    """
    统一的聊天完成端点
    支持通过 model_id 或 model_require 选择模型
    
    Auto 模式智能选择：
    - 自动检测消息中是否包含图像
    - 有图像时自动切换到 VLM
    - 无图像时使用普通 LLM
    """
    # 先获取用户ID（模型选择需要用到）
    user_id = _get_user_id(request)
    
    actual_model_id = _resolve_model_for_request(req, request, user_id)

    logger.info(f"Received chat request: model={req.model} (actual={actual_model_id}), stream={req.stream}, max_tokens={req.max_tokens}")
    log_structured(
        "Chat", "chat_request",
        model_id=actual_model_id, stream=req.stream, message_count=len(req.messages or []), max_tokens=req.max_tokens,
    )

    (
        user_text,
        session_id,
        persistence_mode,
        last_user_msg,
        _should_create_session,
        request_id,
        _force_new_session,
    ) = _prepare_chat_request_state(
        req=req,
        request=request,
        actual_model_id=actual_model_id,
        user_id=user_id,
    )

    # Trace / IDs (必须提前初始化，避免 RAG 分支失败导致变量不存在)
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    message_id = f"msg_{uuid.uuid4().hex[:16]}"

    trace_id, retrieved_count = await _prepare_chat_runtime_context(
        req=req,
        user_id=user_id,
        session_id=session_id,
        actual_model_id=actual_model_id,
        user_text=user_text,
        persistence_mode=persistence_mode,
        last_user_msg=last_user_msg,
        request_id=request_id,
        message_id=message_id,
    )
        
    # 5. 获取模型 Agent
    agent = get_router().get_agent(actual_model_id)
    
    created_time = int(time.time())
    
    _persist_success_turn = _build_persist_success_turn(
        req=req,
        session_id=session_id,
        user_text=user_text,
        persistence_mode=persistence_mode,
        last_user_msg=last_user_msg,
        request_id=request_id,
        user_id=user_id,
        completion_id=completion_id,
        trace_id=trace_id,
        retrieved_count=retrieved_count,
    )

    if req.stream:
        return _handle_streaming_chat(
            req=req,
            request=request,
            agent=agent,
            session_id=session_id,
            completion_id=completion_id,
            created_time=created_time,
            trace_id=trace_id,
            user_text=user_text,
            user_id=user_id,
            persistence_mode=persistence_mode,
            request_id=request_id,
            conv_manager=conv_manager,
            persist_success_turn=_persist_success_turn,
        )
    return await _handle_nonstream_chat(
        req=req,
        response=response,
        agent=agent,
        session_id=session_id,
        completion_id=completion_id,
        created_time=created_time,
        trace_id=trace_id,
        user_text=user_text,
        user_id=user_id,
        persist_success_turn=_persist_success_turn,
    )


@router.post("/v1/chat/completions/stream/resume")
async def chat_stream_resume(body: ChatStreamResumeBody, request: Request) -> StreamingResponse:
    """从已缓冲的 SSE 帧序列按 chunk 下标继续拉取（断点续传）。"""
    if not bool(getattr(settings, "chat_stream_resume_enabled", True)):
        raise_api_error(status_code=404, code="stream_resume_disabled", message="断点续传未开启")
    user_id = _get_user_id(request)
    store = get_stream_resume_store()
    sess = store.get(body.stream_id)
    if not sess or sess.user_id != user_id:
        raise_api_error(status_code=404, code="stream_not_found", message="流不存在或已过期")

    wait_timeout = float(getattr(settings, "chat_stream_resume_wait_timeout_seconds", 120) or 120)

    stream_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    async def _gen() -> AsyncIterator[str]:
        try:
            async for piece in iter_resume_chunks(
                store,
                body.stream_id,
                body.chunk_index,
                wait_timeout=wait_timeout,
            ):
                yield piece
        except asyncio.TimeoutError:
            yield _stream_build_chunk(
                completion_id=sess.completion_id or "chatcmpl-unknown",
                created_time=int(sess.sse_created or sess.created_at),
                model_id=sess.model_id or "unknown",
                content="\nError: stream resume wait timeout",
            )
            yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=stream_headers)
