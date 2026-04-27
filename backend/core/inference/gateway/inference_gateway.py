"""
V2.8 Inference Gateway Layer - Inference Gateway

Central inference routing hub.
Coordinates ModelRouter and ProviderRuntimeAdapter.
"""
from typing import Any, AsyncIterator, Optional
import hashlib
import json
import time

from log import logger
from config.settings import settings
from core.cache import get_memory_cache_client, get_redis_cache_client
from core.models.registry import get_model_registry
from core.events import get_event_bus

from core.inference.router.model_router import ModelRouter, RoutingResult
from core.inference.providers.provider_runtime_adapter import ProviderRuntimeAdapter
from core.inference.models.inference_request import InferenceRequest
from core.inference.models.inference_response import InferenceResponse
from core.inference.models.embedding_request import EmbeddingRequest
from core.inference.models.embedding_response import EmbeddingResponse
from core.inference.models.asr_request import ASRRequest
from core.inference.models.asr_response import ASRResponse
from core.inference.stats import (
    get_inference_stats,
    record_inference_cache_hit,
    record_inference_cache_miss,
)
from core.observability import get_prometheus_business_metrics


class InferenceGateway:
    """
    Central inference routing hub.
    
    Coordinates:
    1. Model alias resolution (ModelRouter)
    2. Provider dispatch (ProviderRuntimeAdapter)
    
    Does NOT:
    - Know about specific models
    - Handle business logic
    - Manage state
    
    Usage:
        gateway = InferenceGateway()
        response = await gateway.generate(request)
    """
    
    def __init__(self) -> None:
        self.router = ModelRouter()
        self.adapter = ProviderRuntimeAdapter()
        self.memory_cache = get_memory_cache_client()
        self.cache = get_redis_cache_client()
        self.model_registry = get_model_registry()
        self.prom_metrics = get_prometheus_business_metrics()

    @staticmethod
    def _is_admin_request(metadata: dict[str, Any]) -> bool:
        role = str(metadata.get("role") or metadata.get("user_role") or "").strip().lower()
        return bool(metadata.get("is_admin")) or role in {"admin", "platform_admin"}

    @staticmethod
    def _apply_request_priority(request: Any) -> None:
        meta = getattr(request, "metadata", {}) or {}
        if InferenceGateway._is_admin_request(meta):
            request.priority = "high"
            meta.setdefault("priority_source", "admin")
            request.metadata = meta

    @staticmethod
    def _hash_payload(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_prefix() -> str:
        return str(getattr(settings, "inference_cache_prefix", "openvitamin:inference") or "openvitamin:inference").strip()

    @staticmethod
    def _safe_key_segment(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "na"
        if len(raw) > 64:
            return hashlib.sha1(raw.encode("utf-8")).hexdigest()
        lowered = raw.lower().replace(":", "_").replace(" ", "_")
        return lowered

    def _cache_scope_prefix(
        self,
        cache_kind: str,
        *,
        user_id: Optional[str] = None,
        model_type: Optional[str] = None,
        resolved_model: Optional[str] = None,
    ) -> str:
        parts = [self._cache_prefix(), cache_kind]
        if user_id:
            parts.append(f"u:{self._safe_key_segment(user_id)}")
        if model_type:
            parts.append(f"mt:{self._safe_key_segment(model_type)}")
        if resolved_model:
            parts.append(f"rm:{self._safe_key_segment(resolved_model)}")
        return ":".join(parts)

    def _build_generate_cache_key(self, routing: RoutingResult, request: InferenceRequest) -> str:
        meta = getattr(request, "metadata", {}) or {}
        user_id = str(meta.get("user_id") or meta.get("x_user_id") or "anonymous")
        model_signature = self._model_cache_signature(routing.model_id)
        payload: dict[str, Any] = {
            "model_alias": request.model_alias,
            "resolved_model": routing.model_id,
            "provider": routing.provider,
            "model_signature": model_signature,
            "user_id": user_id,
            "messages": [m.model_dump() for m in (request.messages or [])],
            "prompt": request.prompt,
            "system_prompt": request.system_prompt,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stop": request.stop or [],
        }
        payload_hash = self._hash_payload(payload)
        model_type = model_signature.get("type", "unknown")
        scope_prefix = self._cache_scope_prefix(
            "generate",
            user_id=user_id,
            model_type=model_type,
            resolved_model=routing.model_id,
        )
        return f"{scope_prefix}:h:{payload_hash}"

    def _build_embedding_cache_key(self, routing: RoutingResult, request: EmbeddingRequest) -> str:
        meta = getattr(request, "metadata", {}) or {}
        user_id = str(meta.get("user_id") or meta.get("x_user_id") or "anonymous")
        model_signature = self._model_cache_signature(routing.model_id)
        embedding_input = request.input if isinstance(request.input, str) else list(request.input)
        payload: dict[str, Any] = {
            "model_alias": request.model_alias,
            "resolved_model": routing.model_id,
            "provider": routing.provider,
            "model_signature": model_signature,
            "user_id": user_id,
            "input": embedding_input,
        }
        payload_hash = self._hash_payload(payload)
        model_type = model_signature.get("type", "unknown")
        scope_prefix = self._cache_scope_prefix(
            "embedding",
            user_id=user_id,
            model_type=model_type,
            resolved_model=routing.model_id,
        )
        return f"{scope_prefix}:h:{payload_hash}"

    @staticmethod
    def _parse_ttl_overrides(raw_json: str) -> dict[str, int]:
        try:
            parsed = json.loads(raw_json or "{}")
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in parsed.items():
            if not isinstance(key, str):
                continue
            try:
                ttl = int(value)
            except Exception:
                continue
            if ttl > 0:
                out[key.strip().lower()] = ttl
        return out

    def _model_cache_signature(self, model_id: str) -> dict[str, str]:
        descriptor = self.model_registry.get_model(model_id)
        if descriptor is None:
            return {
                "id": model_id,
                "type": "unknown",
                "provider": "unknown",
                "version": "unknown",
            }
        version = (descriptor.version or "").strip() or "unknown"
        return {
            "id": descriptor.id,
            "type": descriptor.model_type,
            "provider": descriptor.provider,
            "version": version,
        }

    def _resolve_generate_cache_ttl(self, routing: RoutingResult) -> int:
        base_ttl = max(1, int(getattr(settings, "inference_cache_ttl_seconds", 300)))
        signature = self._model_cache_signature(routing.model_id)
        model_type = signature.get("type", "unknown").lower()
        overrides = self._parse_ttl_overrides(
            str(getattr(settings, "inference_cache_ttl_by_model_type_json", "") or "")
        )
        return max(1, int(overrides.get(model_type, base_ttl)))

    async def _emit_inference_completed(
        self,
        *,
        request: InferenceRequest,
        routing: RoutingResult,
        cache_hit: bool,
    ) -> None:
        try:
            meta = getattr(request, "metadata", {}) or {}
            await get_event_bus().publish(
                event_type="inference.completed",
                source="inference_gateway",
                payload={
                    "model_alias": request.model_alias,
                    "resolved_model": routing.model_id,
                    "provider": routing.provider,
                    "resolved_via": routing.resolved_via,
                    "cache_hit": cache_hit,
                    "session_id": meta.get("session_id"),
                    "trace_id": meta.get("trace_id"),
                    "agent_id": meta.get("agent_id"),
                },
            )
        except Exception as e:
            logger.debug("[InferenceGateway] emit inference.completed failed: %s", e)

    async def clear_cache(
        self,
        *,
        cache_kind: str = "generate",
        user_id: Optional[str] = None,
        model_type: Optional[str] = None,
        resolved_model: Optional[str] = None,
        model_alias: Optional[str] = None,
    ) -> dict[str, Any]:
        target_resolved_model = resolved_model
        if not target_resolved_model and model_alias:
            try:
                target_resolved_model = self.router.resolve(model_alias).model_id
            except Exception:
                target_resolved_model = model_alias
        scoped_prefix = self._cache_scope_prefix(
            cache_kind,
            user_id=user_id,
            model_type=model_type,
            resolved_model=target_resolved_model,
        )
        memory_deleted = self.memory_cache.clear_prefix(scoped_prefix)
        redis_deleted = await self.cache.clear_prefix(scoped_prefix)
        return {
            "cache_kind": cache_kind,
            "prefix": scoped_prefix,
            "model_alias": model_alias,
            "resolved_model": target_resolved_model,
            "memory_deleted": memory_deleted,
            "redis_deleted": redis_deleted,
            "total_deleted": memory_deleted + redis_deleted,
        }

    def get_cache_stats(self) -> dict[str, Any]:
        return get_inference_stats().get_stats()

    @staticmethod
    def _validate_messages(request: InferenceRequest) -> None:
        """
        Deterministic guards for message-first requests.

        - Do not reorder messages (User-in-Control).
        - Validate common provider constraints early.
        - Prevent obvious prompt bloat (e.g., huge data URLs) from crashing runtimes.
        """
        messages = getattr(request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return

        # Basic prompt bloat guard: prevent pathological payloads from crashing runtimes.
        total_text_chars = 0
        total_image_url_chars = 0

        # Many chat templates require system messages to be at the beginning.
        saw_non_system = False
        for m in messages:
            role = getattr(m, "role", None) if not isinstance(m, dict) else m.get("role")
            if role == "system":
                if saw_non_system:
                    raise ValueError("System message must be at the beginning.")
            else:
                saw_non_system = True

            content = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
            if isinstance(content, str):
                total_text_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    item_type = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                    if item_type != "image_url":
                        if item_type == "text":
                            text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
                            if isinstance(text, str):
                                total_text_chars += len(text)
                        continue
                    image_url = getattr(item, "image_url", None) if not isinstance(item, dict) else item.get("image_url")
                    url = (image_url or {}).get("url", "") if isinstance(image_url, dict) else ""
                    if isinstance(url, str):
                        total_image_url_chars += len(url)
                    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
                        raise ValueError("image_url must be a data URL (data:image/...) in this deployment.")
                    if isinstance(url, str) and url.startswith("data:image/") and len(url) > 2_000_000:
                        raise ValueError("image_url data URL is too large; provide a workspace file reference instead.")

        if total_text_chars > 200_000:
            raise ValueError("messages text content too large; reduce context or chunk the request.")
        if total_image_url_chars > 6_000_000:
            raise ValueError("messages image content too large; reduce image size or number of images.")
    
    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Execute non-streaming inference.
        
        Args:
            request: InferenceRequest with model_alias and prompt
            
        Returns:
            InferenceResponse with generated text
        """
        self._validate_messages(request)
        self._apply_request_priority(request)
        operation = "generate"
        started_at = time.perf_counter()
        self.prom_metrics.observe_inference_started(operation=operation)
        provider_name = "unknown"
        try:
            routing = self.router.resolve(request.model_alias, request_metadata=request.metadata)
            provider_name = routing.provider
            meta = getattr(request, "metadata", {}) or {}
            logger.info(
                "[InferenceGateway] Routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
                request.model_alias,
                routing.provider,
                routing.model_id,
                routing.resolved_via,
                meta.get("session_id"),
                meta.get("trace_id"),
                meta.get("agent_id"),
            )

            cache_key = self._build_generate_cache_key(routing, request)
            cache_ttl = self._resolve_generate_cache_ttl(routing)
            generate_started_at = time.time()
            cached = self.memory_cache.get_json(cache_key)
            if not cached:
                cached = await self.cache.get_json(cache_key)
                if cached:
                    self.memory_cache.set_json(cache_key, cached, cache_ttl)
            if cached:
                try:
                    response = InferenceResponse(**cached)
                    saved_latency_ms = max(0.0, (time.time() - generate_started_at) * 1000.0)
                    record_inference_cache_hit(saved_latency_ms=saved_latency_ms)
                    response.metadata = {
                        **(response.metadata or {}),
                        "cache_hit": True,
                        "cache_layer": "memory_or_redis",
                        "cache_saved_latency_ms": round(saved_latency_ms, 2),
                    }
                    await self._emit_inference_completed(request=request, routing=routing, cache_hit=True)
                    self.prom_metrics.observe_inference_finished(
                        operation=operation,
                        provider=routing.provider,
                        model=routing.model_id,
                        latency_seconds=(time.perf_counter() - started_at),
                    )
                    return response
                except Exception:
                    pass
            record_inference_cache_miss()

            if routing.resolved_via == "direct":
                response = await self.adapter.generate("auto", request.model_alias, request)
            else:
                response = await self.adapter.generate(routing.provider, routing.model_id, request)

            response.metadata = {**(response.metadata or {}), "cache_hit": False}
            self.memory_cache.set_json(cache_key, response.model_dump(), cache_ttl)
            await self.cache.set_json(cache_key, response.model_dump(), cache_ttl)
            await self._emit_inference_completed(request=request, routing=routing, cache_hit=False)
            self.prom_metrics.observe_inference_finished(
                operation=operation,
                provider=routing.provider,
                model=routing.model_id,
                latency_seconds=(time.perf_counter() - started_at),
            )
            return response
        except Exception:
            self.prom_metrics.observe_inference_failed(operation=operation, provider=provider_name)
            raise

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self._apply_request_priority(request)
        operation = "embed"
        started_at = time.perf_counter()
        self.prom_metrics.observe_inference_started(operation=operation)
        provider_name = "unknown"
        try:
            routing = self.router.resolve(request.model_alias, request_metadata=request.metadata)
            provider_name = routing.provider
            meta = getattr(request, "metadata", {}) or {}
            logger.info(
                "[InferenceGateway] Embed routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
                request.model_alias,
                routing.provider,
                routing.model_id,
                routing.resolved_via,
                meta.get("session_id"),
                meta.get("trace_id"),
                meta.get("agent_id"),
            )
            cache_key = self._build_embedding_cache_key(routing, request)
            cache_ttl = max(1, int(getattr(settings, "embedding_cache_ttl_seconds", 86400)))
            cached = self.memory_cache.get_json(cache_key)
            if not cached:
                cached = await self.cache.get_json(cache_key)
                if cached:
                    self.memory_cache.set_json(cache_key, cached, cache_ttl)
            if cached:
                try:
                    response = EmbeddingResponse(**cached)
                    record_inference_cache_hit()
                    response.metadata = {**(response.metadata or {}), "cache_hit": True, "cache_layer": "memory_or_redis"}
                    self.prom_metrics.observe_inference_finished(
                        operation=operation,
                        provider=routing.provider,
                        model=routing.model_id,
                        latency_seconds=(time.perf_counter() - started_at),
                    )
                    return response
                except Exception:
                    pass
            record_inference_cache_miss()

            if routing.resolved_via == "direct":
                response = await self.adapter.embed("auto", request.model_alias, request)
            else:
                response = await self.adapter.embed(routing.provider, routing.model_id, request)
            response.metadata = {**(response.metadata or {}), "cache_hit": False}
            self.memory_cache.set_json(cache_key, response.model_dump(), cache_ttl)
            await self.cache.set_json(cache_key, response.model_dump(), cache_ttl)
            self.prom_metrics.observe_inference_finished(
                operation=operation,
                provider=routing.provider,
                model=routing.model_id,
                latency_seconds=(time.perf_counter() - started_at),
            )
            return response
        except Exception:
            self.prom_metrics.observe_inference_failed(operation=operation, provider=provider_name)
            raise

    async def transcribe(self, request: ASRRequest) -> ASRResponse:
        operation = "transcribe"
        started_at = time.perf_counter()
        self.prom_metrics.observe_inference_started(operation=operation)
        provider_name = "unknown"
        try:
            routing = self.router.resolve(
                request.model_alias,
                request_metadata=getattr(request, "metadata", {}) or {},
            )
            provider_name = routing.provider
            meta = getattr(request, "metadata", {}) or {}
            logger.info(
                "[InferenceGateway] ASR routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
                request.model_alias,
                routing.provider,
                routing.model_id,
                routing.resolved_via,
                meta.get("session_id"),
                meta.get("trace_id"),
                meta.get("agent_id"),
            )
            if routing.resolved_via == "direct":
                response = await self.adapter.transcribe("auto", request.model_alias, request)
            else:
                response = await self.adapter.transcribe(routing.provider, routing.model_id, request)
            self.prom_metrics.observe_inference_finished(
                operation=operation,
                provider=routing.provider,
                model=routing.model_id,
                latency_seconds=(time.perf_counter() - started_at),
            )
            return response
        except Exception:
            self.prom_metrics.observe_inference_failed(operation=operation, provider=provider_name)
            raise
    
    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """
        Execute streaming inference.
        
        Args:
            request: InferenceRequest with model_alias and prompt
            
        Yields:
            Token strings
        """
        self._validate_messages(request)
        self._apply_request_priority(request)
        operation = "stream"
        started_at = time.perf_counter()
        self.prom_metrics.observe_inference_started(operation=operation)
        routing = self.router.resolve(request.model_alias, request_metadata=request.metadata)
        
        meta = getattr(request, "metadata", {}) or {}
        logger.info(
            "[InferenceGateway] Stream routing alias=%s -> %s/%s via=%s session_id=%s trace_id=%s agent_id=%s",
            request.model_alias,
            routing.provider,
            routing.model_id,
            routing.resolved_via,
            meta.get("session_id"),
            meta.get("trace_id"),
            meta.get("agent_id"),
        )
        
        # 2. Stream via adapter
        try:
            if routing.resolved_via == "direct":
                async for token in self.adapter.stream(
                    "auto",
                    request.model_alias,
                    request
                ):
                    yield token
            else:
                async for token in self.adapter.stream(
                    routing.provider,
                    routing.model_id,
                    request
                ):
                    yield token
        except Exception:
            self.prom_metrics.observe_inference_failed(operation=operation, provider=routing.provider)
            raise
        else:
            self.prom_metrics.observe_inference_finished(
                operation=operation,
                provider=routing.provider,
                model=routing.model_id,
                latency_seconds=(time.perf_counter() - started_at),
            )
    
    def get_routing_info(self, model_alias: str) -> RoutingResult:
        """
        Get routing information without executing inference.
        
        Args:
            model_alias: The alias to resolve
            
        Returns:
            RoutingResult with resolution details
        """
        return self.router.resolve(model_alias)
    
    def list_available_models(self) -> list[str]:
        """List all available model aliases"""
        return self.router.list_available_models()


# Singleton
_gateway: Optional[InferenceGateway] = None


def get_inference_gateway() -> InferenceGateway:
    """Get the global InferenceGateway singleton"""
    global _gateway
    if _gateway is None:
        _gateway = InferenceGateway()
    return _gateway
