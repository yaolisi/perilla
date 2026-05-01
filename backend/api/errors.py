from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.error_i18n import localize_error_message, resolve_accept_language_for_sse
from config.settings import settings
from log import logger


class ApiErrorDetailsJsonMap(BaseModel):
    """统一错误响应 error.details 中的自由 JSON 对象。"""

    model_config = ConfigDict(extra="allow")


class APIError(BaseModel):
    code: str = Field(default="api_error")
    message: str
    details: Optional[ApiErrorDetailsJsonMap] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None


class APIErrorHttpEnvelope(BaseModel):
    """与 APIException / HTTPException handler 返回体一致，用于 OpenAPI 声明 4xx JSON 形状。"""

    detail: str
    error: APIError


class APIException(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details) if details else None


_http_exception_fallback_observer: Optional[
    Callable[[int, str, str], None]
] = None


def set_http_exception_fallback_observer(
    observer: Optional[Callable[[int, str, str], None]],
) -> None:
    """Set test-only observer for HTTPException fallback hits."""
    global _http_exception_fallback_observer
    _http_exception_fallback_observer = observer


def build_api_error_detail(
    *,
    code: str,
    message: str,
    details: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if details:
        payload["details"] = dict(details)
    return payload


def raise_api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    raise APIException(
        status_code=status_code,
        code=code,
        message=message,
        details=details,
    )


_STRUCTURED_HTTP_DETAIL_KEYS = frozenset({"code", "message", "details"})


def _structured_http_exception_parts(detail: Dict[str, Any]) -> tuple[str, str, Optional[Dict[str, Any]]]:
    """解析 ``HTTPException(detail={code, message, ...})``；顶层除 code/message/details 外的键并入 ``details``。"""
    message = str(detail.get("message", "request failed"))
    code = str(detail.get("code", "http_error"))
    nested = detail.get("details")
    extras = {k: v for k, v in detail.items() if k not in _STRUCTURED_HTTP_DETAIL_KEYS}
    if isinstance(nested, dict):
        merged: Optional[Dict[str, Any]] = {**nested, **extras} if extras else nested
    elif extras:
        merged = extras
    else:
        merged = nested if isinstance(nested, dict) else None
    return code, message, merged


def register_error_handlers(app: FastAPI) -> None:
    def _accept_lang_for_request(request: Request) -> str | None:
        return resolve_accept_language_for_sse(request, request.query_params.get("lang"))

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """生产环境（debug=false）不返回 Pydantic loc/type 等细节，避免泄露内部字段结构。"""
        if getattr(settings, "debug", False):
            return JSONResponse(status_code=422, content={"detail": exc.errors()})
        localized_message = localize_error_message(
            code="request_validation_error",
            default_message="Request validation failed",
            accept_language=_accept_lang_for_request(request),
        )
        error = APIError(
            code="request_validation_error",
            message=localized_message,
            details=None,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": localized_message,
                "error": error.model_dump(exclude_none=True),
            },
        )

    @app.exception_handler(APIException)
    async def _api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
        localized_message = localize_error_message(
            code=exc.code,
            default_message=exc.message,
            accept_language=_accept_lang_for_request(request),
        )
        error = APIError(
            code=exc.code,
            message=localized_message,
            details=exc.details,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": localized_message,
                "error": error.model_dump(exclude_none=True),
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            code, message, extra_details = _structured_http_exception_parts(detail)
        else:
            message = str(detail)
            # Fallback path: framework/third-party HTTPException without APIException envelope.
            code = f"http_unexpected_{exc.status_code}"
            extra_details = {"source": "http_exception_fallback"}
            if _http_exception_fallback_observer is not None:
                try:
                    _http_exception_fallback_observer(
                        exc.status_code,
                        message,
                        request.url.path,
                    )
                except Exception:
                    logger.debug("[APIError] fallback observer failed", exc_info=True)
            logger.warning(
                "[APIError] Fallback HTTPException captured status=%s detail=%s path=%s",
                exc.status_code,
                message,
                request.url.path,
            )

        localized_message = localize_error_message(
            code=code,
            default_message=message,
            accept_language=_accept_lang_for_request(request),
        )
        error = APIError(
            code=code,
            message=localized_message,
            details=extra_details if isinstance(extra_details, dict) else None,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": localized_message,
                "error": error.model_dump(exclude_none=True),
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "[APIError] Unhandled exception path=%s",
            request.url.path,
        )
        localized_message = localize_error_message(
            code="internal_server_error",
            default_message="Internal server error",
            accept_language=_accept_lang_for_request(request),
        )
        err_details: Optional[Dict[str, Any]] = None
        if getattr(settings, "debug", False):
            err_details = {"exception": exc.__class__.__name__}
        error = APIError(
            code="internal_server_error",
            message=localized_message,
            details=err_details,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": localized_message,
                "error": error.model_dump(exclude_none=True),
            },
        )
