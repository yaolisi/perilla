from __future__ import annotations

from collections.abc import Iterator

import pytest

from api.errors import set_http_exception_fallback_observer


@pytest.fixture()
def fallback_probe() -> Iterator[list[tuple[int, str, str]]]:
    events: list[tuple[int, str, str]] = []

    def _observer(status: int, message: str, path: str) -> None:
        events.append((status, message, path))

    set_http_exception_fallback_observer(_observer)
    try:
        yield events
    finally:
        set_http_exception_fallback_observer(None)
