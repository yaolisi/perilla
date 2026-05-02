"""
VLM API 端点
提供 image + text → text 的多模态推理服务
"""

import json
import base64
import time
from typing import cast, Optional, Any
from pathlib import Path
from fastapi import APIRouter, UploadFile, Form, File, Request, Response
from pydantic import BaseModel, Field
from log import logger
from api.errors import raise_api_error
from config.settings import settings

from core.types import ChatCompletionUsage
from core.models.descriptor import ModelDescriptor
from core.runtimes.vlm_runtime import VLMRuntime
from core.runtimes.factory import get_runtime_factory
from core.inference.router.model_router import ModelRouter
from core.models.selector import get_model_selector
from core.conversation.history_store import HistoryStore, HistoryStoreConfig
from core.runtime.queue.inference_queue import get_inference_queue_manager
from core.runtime.manager.runtime_metrics import get_runtime_metrics
from core.inference.stats.tracker import record_inference, estimate_tokens
from core.system.runtime_settings import get_auto_unload_local_model_on_switch
from log import log_structured
from core.utils.tenant_request import get_effective_tenant_id

router = APIRouter()

# Use consistent DB path with other session APIs
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)
_history_store = HistoryStore(
    HistoryStoreConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
        vector_enabled=bool(settings.memory_vector_enabled),
    )
)


def _get_user_id(req: Request) -> str:
    uid = (req.headers.get("X-User-Id") or "").strip()
    return uid or "default"


def _get_or_create_session_id(
    *,
    store: HistoryStore,
    req: Request,
    user_id: str,
    title_hint: str,
    model_id: str,
    tenant_id: str,
) -> str:
    sid = (req.headers.get("X-Session-Id") or "").strip()
    if sid and store.session_exists(user_id=user_id, session_id=sid, tenant_id=tenant_id):
        return sid
    title = (title_hint or "").strip()
    if not title:
        title = "New Chat"
    else:
        title = title[:50]
    return cast(
        str,
        store.create_session(user_id=user_id, title=title, last_model=model_id, tenant_id=tenant_id),
    )


async def _maybe_unload_previous_model(
    *, store: HistoryStore, user_id: str, session_id: str, current_model_id: str, tenant_id: str
) -> None:
    try:
        session = store.get_session(user_id=user_id, session_id=session_id, tenant_id=tenant_id)
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
        logger.info("[VLM API] Unloaded previous model %s before switching to %s", last_model, current_model_id)
    except Exception as e:
        logger.warning("[VLM API] Failed to unload previous model: %s", e)


def _sniff_mime(b: bytes, fallback: str = "image/jpeg") -> str:
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b.startswith(b"RIFF") and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return fallback


def _vlm_routing_request_metadata(request: Request, user_id: str) -> dict[str, Any]:
    """与 chat 的 _chat_routing_request_metadata 对齐：供 ModelRouter 分桶 / 策略使用。"""
    out: dict[str, Any] = {"user_id": user_id, "x_user_id": user_id}
    rid = (request.headers.get("x-request-id") or request.headers.get("X-Request-Id") or "").strip()
    if rid:
        out["request_id"] = rid
    sid = (request.headers.get("X-Session-Id") or "").strip()
    if sid:
        out["session_id"] = sid
    return out


def _routing_submeta_for_persist_vlm(request: Request) -> Optional[dict[str, str]]:
    """从 request.state 取可落库到 message.meta['routing'] 的字段（与 chat 一致）。"""
    raw = getattr(request.state, "chat_routing_metadata", None)
    if not isinstance(raw, dict):
        return None
    rm = raw.get("resolved_model")
    rv = raw.get("resolved_via")
    if rm is None or rv is None or str(rm).strip() == "" or str(rv).strip() == "":
        return None
    return {"resolved_model": str(rm), "resolved_via": str(rv)}


def _vlm_messages_for_model_selection(*, user_prompt: str) -> list[dict[str, Any]]:
    """
    供 ModelSelector 在 auto/模糊路径下使用：带「显式含图」的 OpenAI 多模态结构，
    使 _has_image_content 为 True，从而在 model=auto 时优先 VLM（与真实本接口始终带图一致）。

    仅占位，不参与真实 ChatCompletion；无额外 IO。
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt or ""},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
                    },
                },
            ],
        }
    ]


def _resolve_vlm_model_descriptor(
    request: Request,
    user_id: str,
    raw_model: str,
    user_prompt: str,
) -> ModelDescriptor:
    """
    与 /v1/chat/completions 一致：Inference ModelRouter + ModelSelector，并写入 request.state.chat_routing_metadata。
    """
    selector = get_model_selector()
    messages = _vlm_messages_for_model_selection(user_prompt=user_prompt)
    raw = (raw_model or "").strip() or None
    routing_meta = _vlm_routing_request_metadata(request, user_id)
    model_for_selector: Optional[str] = raw
    inference_via: Optional[str] = None
    if raw and raw != "auto":
        rr = ModelRouter().resolve(raw, request_metadata=routing_meta, max_depth=10)
        model_for_selector = rr.model_id
        inference_via = rr.resolved_via
    descriptor = selector.resolve(
        model_id=model_for_selector,
        model_require=None,
        messages=messages,
    )
    actual_model_id = descriptor.id
    resolved_via = "selector"
    if inference_via is not None:
        resolved_via = inference_via
        if model_for_selector and actual_model_id != model_for_selector:
            resolved_via = f"{inference_via}+registry"
    request.state.chat_routing_metadata = {
        "resolved_model": actual_model_id,
        "resolved_via": resolved_via,
    }
    return descriptor


class VLMGenerateRequest(BaseModel):
    """
    VLM 生成请求模型
    """
    model: str = Field(..., description="VLM 模型 ID")
    prompt: str = Field(..., description="文本提示词", min_length=1)
    system_prompt: Optional[str] = Field(
        default=None,
        description="可选的系统提示词（用于约束模型行为，例如要求必须基于图像回答）",
        max_length=4096,
    )
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2, description="采样温度")
    max_tokens: Optional[int] = Field(default=512, ge=1, le=8192, description="最大生成 token 数")


class VlmGenerateRoutingMetadata(BaseModel):
    """与 /v1/chat/completions 对齐的智能路由说明（resolved_model / resolved_via）。"""

    resolved_model: str
    resolved_via: str


class VLMGenerateResponse(BaseModel):
    """
    VLM 生成响应模型
    """
    model: str = Field(..., description="使用的模型 ID")
    text: str = Field(..., description="生成的文本结果")
    usage: Optional[ChatCompletionUsage] = Field(default=None, description="使用统计信息（token 估算）")
    metadata: Optional[VlmGenerateRoutingMetadata] = Field(
        default=None,
        description="与 /v1/chat/completions 对齐：智能路由结果 resolved_model / resolved_via",
    )


@router.post("/v1/vlm/generate", response_model=VLMGenerateResponse)
async def vlm_generate(
    request: Request,
    response: Response,
    request_json: str = Form(..., alias="request", description="JSON string of VLMGenerateRequest"),
    image: UploadFile = File(..., description="输入图像文件"),
) -> VLMGenerateResponse:
    """
    VLM 多模态推理接口
    
    Args:
        request: VLM 生成请求参数
        image: 上传的图像文件
        
    Returns:
        VLMGenerateResponse: 包含生成文本的响应
        
    Raises:
        结构化错误: 当模型不存在、不是 VLM 模型或推理失败时
        
    设计说明：
    1. 使用 Form + File 分离 JSON 参数和二进制图像数据
    2. 不复用 OpenAI ChatCompletion 协议，采用专为 VLM 设计的简洁接口
    3. 从 ModelRegistry 获取模型信息，通过 RuntimeFactory 获取对应运行时
    4. 调用 VLMRuntime.infer() 执行推理
    5. 不处理鉴权、streaming、模型自动选择（由上层处理）
    """

    # NOTE: FastAPI will inject Request/Response by type, but our parameter names conflict with "request" form field.
    # We therefore retrieve them via dependency injection by name: FastAPI still supports this as long as the types match.
    store = _history_store
    
    logger.info("[VLM API] /v1/vlm/generate request received filename=%r content_type=%r", image.filename, image.content_type)

    # 0. 解析表单中的 JSON 请求参数
    try:
        req_obj = VLMGenerateRequest(**json.loads(request_json))
    except Exception as e:
        raise_api_error(
            status_code=400,
            code="vlm_invalid_request_json",
            message=f"Invalid request JSON: {e}",
        )
    logger.info(
        "[VLM API] parsed request model=%s prompt_len=%s temperature=%s max_tokens=%s",
        req_obj.model, len(req_obj.prompt or ""), req_obj.temperature, req_obj.max_tokens,
    )

    user_id = _get_user_id(request)
    tenant_id = get_effective_tenant_id(request)
    try:
        model_descriptor = _resolve_vlm_model_descriptor(
            request, user_id, req_obj.model, req_obj.prompt
        )
    except ValueError as e:
        raise_api_error(
            status_code=400,
            code="vlm_model_resolve_failed",
            message=str(e),
            details={"model_id": req_obj.model},
        )
    if not _is_vlm_model(model_descriptor):
        raise_api_error(
            status_code=400,
            code="vlm_model_not_vlm",
            message=f"Model '{model_descriptor.id}' is not a VLM model",
            details={"model_id": model_descriptor.id},
        )
    model_id = model_descriptor.id

    # 3. 获取对应的 VLM Runtime（使用单例工厂以复用 VLM runtime 缓存）
    runtime_factory = get_runtime_factory()
    await runtime_factory.auto_release_unused_local_runtimes(
        keep_model_ids={model_id},
        reason="vlm_api",
    )
    try:
        vlm_runtime = await _get_vlm_runtime(model_descriptor, runtime_factory)
    except Exception as e:
        logger.error(f"[VLM API] Failed to get VLM runtime for model {model_id}: {e}")
        raise_api_error(
            status_code=500,
            code="vlm_runtime_init_failed",
            message=f"Failed to initialize VLM runtime: {str(e)}",
            details={"model_id": model_id},
        )
    
    # 4. 读取并验证图像数据（结构化错误需在 ``except Exception`` 之外抛出，避免被误判为读取失败）
    try:
        image_content = await image.read()
    except Exception as e:
        logger.error(f"[VLM API] Failed to read image file: {e}")
        raise_api_error(
            status_code=400,
            code="vlm_invalid_image",
            message=f"Invalid image file: {str(e)}",
        )
    if not image_content:
        raise_api_error(
            status_code=400,
            code="vlm_empty_image",
            message="Empty image file provided",
        )
    logger.info("[VLM API] image bytes read size=%s", len(image_content))
    
    # Session persistence (so /chat sessions won't lose VLM turns)
    session_id: Optional[str] = None
    try:
        session_id = _get_or_create_session_id(
            store=store,
            req=request,
            user_id=user_id,
            title_hint=req_obj.prompt,
            model_id=model_id,
            tenant_id=tenant_id,
        )
        if isinstance(response, Response):
            response.headers["X-Session-Id"] = session_id
        if session_id and get_auto_unload_local_model_on_switch():
            await _maybe_unload_previous_model(
                store=store,
                user_id=user_id,
                session_id=session_id,
                current_model_id=model_id,
                tenant_id=tenant_id,
            )
    except Exception as e:
        logger.warning(f"[VLM API] Failed to get/create session: {e}")
    logger.info("[VLM API] session resolved user_id=%s session_id=%s", user_id, session_id)

    # Build attachment meta for UI (store only meta, keep message content pure text for LLM chat maintainability)
    mime = _sniff_mime(image_content, fallback=(image.content_type or "image/jpeg"))
    data_url = f"data:{mime};base64,{base64.b64encode(image_content).decode('utf-8')}"
    attachments_meta = [{"type": "image", "url": data_url, "name": image.filename or "image"}]

    # Persist user message
    if session_id:
        try:
            rout = _routing_submeta_for_persist_vlm(request)
            umeta: dict[str, Any] = {"attachments": attachments_meta, "vlm": True}
            if rout:
                umeta["routing"] = rout
            store.append_message(
                session_id=session_id,
                role="user",
                content=req_obj.prompt,
                meta=umeta,
                tenant_id=tenant_id,
            )
            store.touch_session(
                user_id=user_id, session_id=session_id, last_model=model_id, tenant_id=tenant_id
            )
        except Exception as e:
            logger.warning(f"[VLM API] Failed to persist user message: {e}")

    # 5. 执行推理
    try:
        async with runtime_factory.model_usage(model_id):
            # 确保运行时已初始化
            if not vlm_runtime.is_loaded:
                logger.info("[VLM API] initializing VLM runtime model=%s runtime=%s", model_id, getattr(model_descriptor, "runtime", None))
                descriptor_meta = model_descriptor.metadata or {}
                model_path = (
                    descriptor_meta.get("model_path")
                    or descriptor_meta.get("path")
                    or model_descriptor.provider_model_id
                    or model_descriptor.id
                )
                await vlm_runtime.initialize(model_path=model_path)
            else:
                logger.info("[VLM API] runtime cache hit model=%s", model_id)
            
            # 执行多模态推理
            logger.info("[VLM API] infer start model=%s", model_id)
            default_system_prompt = (
            "你是一个视觉语言助手。图像已经直接输入到你的视觉编码器中，你可以完全看到图像内容。\n"
            "用户消息中的图像是你当前可以直接观察和理解的视觉输入，不是外部附件或链接。\n"
            "请直接描述和分析图像内容，回答用户的问题。\n"
            "绝对不要说\"我无法查看图像\"、\"无法查看附件\"、\"无法访问外部链接\"等话术。\n"
            "如果图像内容不清晰或难以识别，请描述你能看到的细节，并说明需要用户补充哪些信息。"
            )
            # Runtime Stabilization: per-model concurrency limit + basic metrics.
            queue_manager = get_inference_queue_manager()
            metrics = get_runtime_metrics()
            runtime_type = str(getattr(model_descriptor, "runtime", "") or "default")
            queue = queue_manager.get_queue(model_id, runtime_type)

            start_infer = time.time()
            metrics.record_request(model_id)
            log_structured("RuntimeStabilization", "inference_started", model_id=model_id, runtime=runtime_type)

            result_text = await queue.run(vlm_runtime.infer(
                image=image_content,  # 传递 bytes 数据
                prompt=req_obj.prompt,
                system_prompt=(req_obj.system_prompt or default_system_prompt),
                temperature=req_obj.temperature,
                max_tokens=req_obj.max_tokens
            ))
            latency_ms = (time.time() - start_infer) * 1000
            metrics.record_latency(model_id, latency_ms)
            tokens_est = estimate_tokens(result_text or "")
            metrics.record_tokens(model_id, tokens_est)
            record_inference(tokens=tokens_est, latency_ms=latency_ms, model=model_id, provider=getattr(model_descriptor, "provider", ""))
            log_structured(
                "RuntimeStabilization",
                "inference_completed",
                model_id=model_id,
                runtime=runtime_type,
                latency_ms=round(latency_ms, 2),
                tokens=tokens_est,
            )
        logger.info("[VLM API] infer done model=%s output_len=%s", model_id, len(result_text or ""))
        
        logger.info(f"[VLM API] Generated text for model {model_id}, prompt length: {len(req_obj.prompt)}")
        
    except Exception as e:
        try:
            get_runtime_metrics().record_request_failed(model_id)
            log_structured("RuntimeStabilization", "inference_error", level="error", model_id=model_id, error=str(e)[:300])
        except Exception:
            pass
        logger.error(f"[VLM API] Inference failed for model {model_id}: {e}", exc_info=True)
        raise_api_error(
            status_code=500,
            code="vlm_inference_failed",
            message=f"Inference failed: {str(e)}",
            details={"model_id": model_id},
        )

    # Persist assistant message
    if session_id:
        try:
            rout = _routing_submeta_for_persist_vlm(request)
            ameta: dict[str, Any] = {"vlm": True}
            if rout:
                ameta["routing"] = rout
            store.append_message(
                session_id=session_id,
                role="assistant",
                content=result_text,
                model=model_id,
                meta=ameta,
                tenant_id=tenant_id,
            )
            store.touch_session(
                user_id=user_id, session_id=session_id, last_model=model_id, tenant_id=tenant_id
            )
        except Exception as e:
            logger.warning(f"[VLM API] Failed to persist assistant message: {e}")
    
    # 6. 返回结果（metadata 与 chat 侧一致，便于前端展示智能路由说明）
    _rout = _routing_submeta_for_persist_vlm(request)
    pt_est = len(req_obj.prompt.split())
    ct_est = len(result_text.split())
    return VLMGenerateResponse(
        model=model_id,
        text=result_text,
        usage=ChatCompletionUsage(
            prompt_tokens=pt_est,
            completion_tokens=ct_est,
            total_tokens=pt_est + ct_est,
        ),
        metadata=VlmGenerateRoutingMetadata(**_rout) if _rout else None,
    )


def _is_vlm_model(model_descriptor: ModelDescriptor) -> bool:
    """
    判断模型是否为 VLM 模型
    
    Args:
        model_descriptor: 模型描述符
        
    Returns:
        bool: 是否为 VLM 模型
        
    设计说明：
    根据你的模型管理系统调整此判断逻辑
    可能的判断依据：
    - model_type 字段包含 "vlm" 或 "vision"
    - capabilities 字段包含 "image_to_text"
    - model_name 包含视觉相关关键词
    """
    # Long-term maintainability: prefer explicit modality/type fields; avoid name-based heuristics.
    mt = str(getattr(model_descriptor, "model_type", "") or "").lower().strip()
    if mt:
        return any(x in mt for x in ("vlm", "vision", "multimodal"))

    # Optional: explicit metadata.modality (if your descriptor stores it there)
    md = getattr(model_descriptor, "metadata", None) or {}
    modality = str(md.get("modality") or "").lower().strip()
    if modality:
        return modality in {"vlm", "vision", "multimodal"}

    # Optional: capabilities list (if present)
    capabilities = getattr(model_descriptor, "capabilities", None)
    if isinstance(capabilities, (list, tuple)):
        caps = {str(c).lower().strip() for c in capabilities}
        if {"vision", "image_to_text", "image"} & caps:
            return True

    # Strict default: do NOT guess by model name (prevents accidental misrouting).
    return False


async def _get_vlm_runtime(model_descriptor: ModelDescriptor, factory: Any) -> VLMRuntime:
    """
    获取 VLM 运行时实例
    
    Args:
        model_descriptor: 模型描述符
        factory: 运行时工厂
        
    Returns:
        VLMRuntime: VLM 运行时实例
    """
    # 使用工厂基于 ModelDescriptor 创建 VLM 运行时
    return cast(VLMRuntime, factory.create_vlm_runtime(model_descriptor))


# 使用示例（仅供说明）：
"""
curl -X POST "http://localhost:8000/api/v1/vlm/generate" \\
  -H "Content-Type: multipart/form-data" \\
  -F "request={\"model\": \"qwen3-vl-8b\", \"prompt\": \"Describe this image in detail.\", \"temperature\": 0.7}" \\
  -F "image=@/path/to/image.jpg"

响应示例：
{
  "model": "qwen3-vl-8b",
  "text": "This image shows a beautiful landscape with mountains and a lake...",
  "usage": {
    "prompt_tokens": 6,
    "completion_tokens": 45
  }
}
"""
