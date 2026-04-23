"""
Request whitelist enforcement for API body fields.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel

from config.settings import settings


def _resolve_body_model(route: APIRoute) -> type[BaseModel] | None:
    body_field = getattr(route, "body_field", None)
    if body_field is not None:
        annotation = getattr(getattr(body_field, "field_info", None), "annotation", None)
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation

    body_params = route.dependant.body_params
    if len(body_params) != 1:
        return None
    field = body_params[0]
    model_type = getattr(field, "annotation", None) or getattr(field, "type_", None)
    if isinstance(model_type, type) and issubclass(model_type, BaseModel):
        return model_type
    return None


async def enforce_request_body_whitelist(request: Request) -> None:
    if not bool(getattr(settings, "api_request_whitelist_enabled", True)):
        return
    if request.method.upper() not in {"POST", "PUT", "PATCH"}:
        return

    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        return

    route = request.scope.get("route")
    if not isinstance(route, APIRoute):
        return

    model_type = _resolve_body_model(route)
    if model_type is None:
        return

    raw_body = await request.body()
    if not raw_body:
        return
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return

    if not isinstance(payload, dict):
        return

    allowed_fields = set(model_type.model_fields.keys())
    unknown_fields = sorted([key for key in payload.keys() if key not in allowed_fields])
    if unknown_fields:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "request_unknown_fields",
                "message": "Request contains unknown fields",
                "unknown_fields": unknown_fields,
                "allowed_fields": sorted(allowed_fields),
            },
        )
