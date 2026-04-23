from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from log import logger


class APIError(BaseModel):
    code: str = Field(default="api_error")
    message: str
    details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None


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


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIException)
    async def _api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
        error = APIError(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "error": error.model_dump(exclude_none=True),
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            message = str(detail.get("message", "request failed"))
            code = str(detail.get("code", "http_error"))
            extra_details = detail.get("details")
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

        error = APIError(
            code=code,
            message=message,
            details=extra_details if isinstance(extra_details, dict) else None,
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": message,
                "error": error.model_dump(exclude_none=True),
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        error = APIError(
            code="internal_server_error",
            message="Internal server error",
            details={"exception": exc.__class__.__name__},
            request_id=getattr(request.state, "request_id", None),
            trace_id=getattr(request.state, "trace_id", None),
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error": error.model_dump(exclude_none=True),
            },
        )
