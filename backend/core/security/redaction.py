from __future__ import annotations

from typing import Any


def _mask_secret(value: str, *, keep_prefix: int = 4, keep_suffix: int = 4) -> str:
    text = value or ""
    if len(text) <= (keep_prefix + keep_suffix):
        return "*" * len(text)
    return f"{text[:keep_prefix]}{'*' * (len(text) - keep_prefix - keep_suffix)}{text[-keep_suffix:]}"


def _looks_sensitive_key(key: str, sensitive_tokens: list[str]) -> bool:
    lowered = (key or "").strip().lower()
    return any(token in lowered for token in sensitive_tokens)


def redact_payload(
    payload: Any,
    *,
    sensitive_fields: list[str],
    keep_prefix: int = 4,
    keep_suffix: int = 4,
) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and _looks_sensitive_key(key, sensitive_fields):
                if isinstance(value, str):
                    redacted[key] = _mask_secret(
                        value, keep_prefix=keep_prefix, keep_suffix=keep_suffix
                    )
                elif value is None:
                    redacted[key] = None
                else:
                    redacted[key] = "***"
            else:
                redacted[key] = redact_payload(
                    value,
                    sensitive_fields=sensitive_fields,
                    keep_prefix=keep_prefix,
                    keep_suffix=keep_suffix,
                )
        return redacted
    if isinstance(payload, list):
        return [
            redact_payload(
                item,
                sensitive_fields=sensitive_fields,
                keep_prefix=keep_prefix,
                keep_suffix=keep_suffix,
            )
            for item in payload
        ]
    return payload
