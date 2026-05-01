"""
Hugging Face transformers 流式生成：TextIteratorStreamer + 后台线程调用 model.generate。

用于 Torch VLM（InternVL / Qwen-VL）在保持 AsyncIO 事件循环响应的同时，
按子词片段产出文本，避免整段生成完成后才一次性推送。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterator, Iterable, List, Optional

from log import log_structured

_MAX_NEW_TOKENS_CAP = 32768


def clamp_stream_max_new_tokens(max_new_tokens: int) -> int:
    """与 VLMGenerationConfig 上限对齐，防止异常超大值。"""
    return max(1, min(_MAX_NEW_TOKENS_CAP, int(max_new_tokens)))


def _earliest_stop_index(acc: str, stop: Optional[List[str]]) -> Optional[int]:
    if not stop:
        return None
    earliest: Optional[int] = None
    for s in stop:
        idx = acc.find(s)
        if idx != -1 and (earliest is None or idx < earliest):
            earliest = idx
    return earliest


def emit_stream_chunks(streamer: Iterable[str], stop: Optional[List[str]]) -> Iterator[str]:
    """
    将 HF TextIteratorStreamer（或任意字符串迭代器）转为带 stop 截断的片段序列。
    纯函数，便于单测。
    """
    yielded_chars = 0
    acc = ""
    for text in streamer:
        if not text:
            continue
        acc += text
        cut_at = _earliest_stop_index(acc, stop)
        if cut_at is not None:
            prefix = acc[:cut_at]
            chunk = prefix[yielded_chars:]
            if chunk:
                yield chunk
            return
        yield text
        yielded_chars += len(text)


def finalize_stream_thread(
    thread: threading.Thread,
    error_box: List[BaseException],
    thread_join_timeout_sec: float,
) -> None:
    """
    join generate 线程并处理异常盒；线程仍存活时记结构化错误（无法强制终止 CUDA kernel）。
    """
    thread.join(timeout=float(thread_join_timeout_sec))
    if thread.is_alive():
        log_structured(
            "TorchStreamHF",
            "generation_thread_join_timeout",
            level="error",
            timeout_sec=thread_join_timeout_sec,
        )
    if error_box:
        raise error_box[0]


def iterate_hf_generate_stream(
    model: Any,
    tokenizer: Any,
    inputs: Dict[str, Any],
    *,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    pad_token_id: Optional[int],
    stop: Optional[List[str]] = None,
    thread_join_timeout_sec: float = 600.0,
) -> Iterator[str]:
    """
    同步迭代器：逐段产出 decode 后的增量文本（由 TextIteratorStreamer 定义粒度）。

    stop：命中任一停止串后截断并结束；若停止串跨多个片段，按已拼接缓冲区裁剪。
    thread_join_timeout_sec：generate 线程 join 超时；超时仍存活则写结构化日志并尽力抛出 error_box 内异常。
    """
    try:
        from transformers import TextIteratorStreamer
    except ImportError as e:
        raise RuntimeError("transformers TextIteratorStreamer 不可用，无法启用 Torch 流式生成") from e

    max_new_tokens = clamp_stream_max_new_tokens(max_new_tokens)
    do_sample = temperature > 0
    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
    )
    gen_kwargs: Dict[str, Any] = {
        **inputs,
        "max_new_tokens": int(max_new_tokens),
        "do_sample": do_sample,
        "pad_token_id": pad_token_id,
        "streamer": streamer,
    }
    if do_sample:
        gen_kwargs["temperature"] = float(temperature)
        gen_kwargs["top_p"] = float(top_p)
    else:
        gen_kwargs["temperature"] = None
        gen_kwargs["top_p"] = None

    error_box: List[BaseException] = []

    def _run_generate() -> None:
        try:
            import torch

            with torch.no_grad():
                model.generate(**gen_kwargs)
        except Exception as e:
            error_box.append(e)

    thread = threading.Thread(target=_run_generate, daemon=True)
    thread.start()

    try:
        yield from emit_stream_chunks(streamer, stop)
    finally:
        finalize_stream_thread(thread, error_box, thread_join_timeout_sec)
