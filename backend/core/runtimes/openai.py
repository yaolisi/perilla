import httpx
import json
from typing import AsyncIterator, Optional, Dict, Any, cast
from log import logger
from core.runtimes.base import ModelRuntime
from core.types import ChatCompletionRequest
from core.models.descriptor import ModelDescriptor

STREAM_DONE_SENTINEL = "[DONE]"


class OpenAIRuntime(ModelRuntime):
    """
    OpenAI 兼容运行时实现
    适用于 OpenAI, LM Studio, DeepSeek 等
    """
    def __init__(self, api_key: str = "sk-not-needed"):
        self.api_key = api_key

    def _get_base_url(self, descriptor: ModelDescriptor) -> str:
        base_url = descriptor.base_url or "http://localhost:1234"
        # 如果是已知云服务商，且已经包含了特定路径，不要强制加 /v1
        cloud_special_paths = ["/v1beta/openai", "/v1"]
        if any(path in base_url for path in cloud_special_paths):
            return base_url.rstrip("/")
        
        # 为本地/远程 LM Studio 和其他 OpenAI 兼容服务添加 /v1 路径
        if not base_url.endswith("/v1"):
            base_url = f"{base_url.rstrip('/')}/v1"
        return base_url.rstrip("/")

    async def chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> str:
        headers = self._get_headers(descriptor)
        payload = self._get_payload(descriptor, req, stream=False)
        
        base_url = self._get_base_url(descriptor)
            
        async with httpx.AsyncClient(timeout=60.0, proxy=None, trust_env=False) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return cast(str, content)

    async def stream_chat(self, descriptor: ModelDescriptor, req: ChatCompletionRequest) -> AsyncIterator[str]:
        headers = self._get_headers(descriptor)
        payload = self._get_payload(descriptor, req, stream=True)
        
        base_url = self._get_base_url(descriptor)
            
        logger.debug(f"[OpenAIRuntime] Streaming from {base_url} with payload model: {payload['model']}")
        
        async with httpx.AsyncClient(timeout=None, proxy=None, trust_env=False) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"[OpenAIRuntime] Error {response.status_code}: {error_text.decode()}")
                        raise RuntimeError(
                            f"OpenAI runtime stream error: {response.status_code} - {error_text.decode()}"
                        )
                    
                    async for line in response.aiter_lines():
                        content = self._extract_stream_content(line)
                        if content is None:
                            continue
                        if content == STREAM_DONE_SENTINEL:
                            break
                        yield content
            except Exception as e:
                logger.error(f"[OpenAIRuntime] Stream failed: {str(e)}")
                raise

    def _get_headers(self, descriptor: ModelDescriptor) -> Dict[str, str]:
        # 从 metadata 中获取 api_key，如果不存在则使用默认值
        api_key = descriptor.metadata.get("api_key") or self.api_key
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def is_loaded(self, descriptor: ModelDescriptor) -> bool:
        """
        OpenAI 兼容运行时通常视为已加载（云端模型或长驻服务）
        如果提供了 base_url 且不是本地开发地址，则直接返回 True
        """
        # 云端模型提供商
        cloud_providers = ["openai", "gemini", "deepseek", "kimi"]
        if descriptor.provider in cloud_providers or descriptor.runtime in cloud_providers:
            return True
        # 对于本地服务，保持“尽量不阻塞 UI”的策略；仅在明显缺失关键信息时返回 False。
        return bool(descriptor.base_url or descriptor.provider_model_id)

    def _get_payload(self, descriptor: ModelDescriptor, req: ChatCompletionRequest, stream: bool) -> Dict[str, Any]:
        return {
            "model": descriptor.provider_model_id,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "top_p": req.top_p,
            "max_tokens": req.max_tokens,
            "stream": stream
        }

    @staticmethod
    def _extract_stream_content(line: str) -> Optional[str]:
        if not line or not line.startswith("data: "):
            return None
        data_str = line[6:].strip()
        if data_str == STREAM_DONE_SENTINEL:
            return STREAM_DONE_SENTINEL
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            return None
        choices = chunk.get("choices", [])
        if not choices:
            return None
        delta = choices[0].get("delta", {})
        content = delta.get("content")
        if isinstance(content, str):
            return content
        return None
