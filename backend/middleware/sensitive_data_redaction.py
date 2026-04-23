"""
Global request/response sensitive-data redaction middleware.
"""
from __future__ import annotations

import json
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config.settings import settings
from core.security.redaction import redact_payload
from log import logger

JSON_MEDIA_TYPE = "application/json"


def _load_sensitive_tokens() -> list[str]:
    raw = (getattr(settings, "data_redaction_sensitive_fields", "") or "").strip()
    tokens = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return tokens or ["api_key", "password", "secret", "token", "authorization"]


def _parse_json_body(raw_body: bytes) -> Any | None:
    if not raw_body:
        return None
    try:
        return json.loads(raw_body.decode("utf-8"))
    except Exception:
        return None


class SensitiveDataRedactionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not bool(getattr(settings, "data_redaction_enabled", True)):
            return await call_next(request)

        sensitive_tokens = _load_sensitive_tokens()
        keep_prefix = int(getattr(settings, "data_redaction_mask_keep_prefix", 4))
        keep_suffix = int(getattr(settings, "data_redaction_mask_keep_suffix", 4))

        request_content_type = (request.headers.get("content-type") or "").lower()
        if JSON_MEDIA_TYPE in request_content_type:
            request_raw_body = await request.body()
            parsed_request = _parse_json_body(request_raw_body)
            if parsed_request is not None:
                request.state.redacted_request_body = redact_payload(
                    parsed_request,
                    sensitive_fields=sensitive_tokens,
                    keep_prefix=keep_prefix,
                    keep_suffix=keep_suffix,
                )

            async def _receive() -> dict[str, Any]:
                return {"type": "http.request", "body": request_raw_body, "more_body": False}

            request._receive = _receive  # type: ignore[attr-defined]

        response = await call_next(request)

        response_content_type = (
            response.headers.get("content-type")
            or getattr(response, "media_type", "")
            or ""
        ).lower()
        if (
            JSON_MEDIA_TYPE not in response_content_type
            or "text/event-stream" in response_content_type
        ):
            return response

        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk

        parsed_response = _parse_json_body(body_bytes)
        if parsed_response is None:
            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=getattr(response, "media_type", None),
            )

        redacted_response = redact_payload(
            parsed_response,
            sensitive_fields=sensitive_tokens,
            keep_prefix=keep_prefix,
            keep_suffix=keep_suffix,
        )
        request_id = getattr(getattr(request, "state", object()), "request_id", "")
        logger.debug("[Redaction] Applied request/response masking request_id=%s", request_id)
        return Response(
            content=json.dumps(redacted_response, ensure_ascii=False),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=JSON_MEDIA_TYPE,
        )
