"""Ingress 示例须保留流式/Keep-Alive 协同调参提示（防注释被删导致生产误配）。"""

from __future__ import annotations

import pytest

from tests.repo_paths import repo_path


@pytest.mark.requires_monorepo
def test_ingress_example_documents_streaming_and_keepalive_hints() -> None:
    p = repo_path("deploy/k8s/ingress-backend.example.yaml")
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "proxy-read-timeout" in text
    assert "UVICORN_TIMEOUT_KEEP_ALIVE_SECONDS" in text
    assert "CHAT_STREAM_WALL_CLOCK_MAX_SECONDS" in text
