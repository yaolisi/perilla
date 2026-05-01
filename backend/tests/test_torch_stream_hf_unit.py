"""Torch HF 流式纯函数与线程收尾（生产级单测，不加载真实模型）。"""

import threading
from unittest.mock import MagicMock

import pytest

from core.runtimes.torch.stream_hf import (
    clamp_stream_max_new_tokens,
    emit_stream_chunks,
    finalize_stream_thread,
)
from core.runtimes.torch.torch_vlm_runtime import _make_stream_queue, _put_stream_item


def test_clamp_stream_max_new_tokens() -> None:
    assert clamp_stream_max_new_tokens(0) == 1
    assert clamp_stream_max_new_tokens(100) == 100
    assert clamp_stream_max_new_tokens(999_999) == 32768


def test_emit_stream_chunks_stop() -> None:
    out = list(emit_stream_chunks(iter(["xx", "STOP", "tail"]), stop=["STOP"]))
    assert out == ["xx"]
    assert "STOP" not in "".join(out)


def test_emit_stream_chunks_no_stop() -> None:
    assert list(emit_stream_chunks(iter(["a", "b"]), None)) == ["a", "b"]


def test_finalize_stream_thread_raises() -> None:
    th = MagicMock(spec=threading.Thread)
    th.join = lambda timeout=None: None
    th.is_alive = lambda: False
    err = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        finalize_stream_thread(th, [err], 1.0)


def test_make_stream_queue_unbounded_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.runtimes.torch.torch_vlm_runtime.get_torch_stream_chunk_queue_max",
        lambda: 0,
    )
    q, bounded = _make_stream_queue()
    assert bounded is False
    assert type(q).__name__ == "SimpleQueue"


def test_make_stream_queue_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.runtimes.torch.torch_vlm_runtime.get_torch_stream_chunk_queue_max",
        lambda: 8,
    )
    q, bounded = _make_stream_queue()
    assert bounded is True
    assert q.maxsize == 8


def test_put_stream_item_bounded_drops_oldest() -> None:
    from queue import Queue

    q: Queue = Queue(maxsize=2)
    _put_stream_item(q, ("a", 1), bounded=True)
    _put_stream_item(q, ("a", 2), bounded=True)
    _put_stream_item(q, ("a", 3), bounded=True)
    assert q.get() == ("a", 2)
    assert q.get() == ("a", 3)
