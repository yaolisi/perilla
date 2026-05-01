"""Multi-hop RAG helpers: shared runtime (core.rag.runtime_multi_hop)."""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.rag.runtime_multi_hop import (
    expand_query_with_feedback,
    last_user_message_only,
    merge_chunks_into,
    run_multi_hop_retrieval,
)


def _key(item: Dict[str, Any]) -> str:
    return (
        f'{item.get("knowledge_base_id", "")}::'
        f'{item.get("document_id", "")}::'
        f'{item.get("chunk_id", "")}'
    )


def test_merge_chunk_rounds_keeps_best_score() -> None:
    a = {
        "knowledge_base_id": "kb1",
        "document_id": "d1",
        "chunk_id": "c1",
        "content": "hello",
        "relevance_score": 0.5,
    }
    b = {
        "knowledge_base_id": "kb1",
        "document_id": "d1",
        "chunk_id": "c1",
        "content": "hello",
        "relevance_score": 0.8,
    }
    merged: Dict[str, Dict[str, Any]] = {}
    merge_chunks_into(merged, [a])
    merge_chunks_into(merged, [b])
    assert len(merged) == 1
    assert merged[_key(a)]["relevance_score"] == 0.8


def test_expand_query_with_feedback_truncates() -> None:
    chunks = [
        {"content": "alpha " * 200, "relevance_score": 0.9},
        {"content": "beta short", "relevance_score": 0.8},
    ]
    q = expand_query_with_feedback(
        base_query="original question",
        merged_chunks_sorted=chunks,
        max_total_chars=120,
        snippet_per_chunk=80,
    )
    assert "original question" in q
    assert len(q) <= 120


def test_fallback_last_user_query() -> None:
    messages = [
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "only this"},
    ]
    assert last_user_message_only(messages, max_length=512) == "only this"


@pytest.mark.asyncio
async def test_multi_hop_stops_when_threshold_met() -> None:
    """Second hop not invoked when first hop satisfies min_chunks + min_best."""
    calls: List[str] = []

    async def fake_embed(q: str) -> List[float]:
        calls.append(q)
        return [0.1] * 8

    chunks_rich = [
        {
            "knowledge_base_id": "kb",
            "document_id": "d1",
            "chunk_id": "c1",
            "content": "x",
            "relevance_score": 0.9,
        },
        {
            "knowledge_base_id": "kb",
            "document_id": "d1",
            "chunk_id": "c2",
            "content": "y",
            "relevance_score": 0.85,
        },
    ]

    async def fake_search(_qt: str, _qe: List[float], _eff: float) -> List[Dict[str, Any]]:
        return list(chunks_rich)

    merged, _detail = await run_multi_hop_retrieval(
        initial_query="user asks",
        rerank_top_k=10,
        min_relevance_score=0.5,
        embed_fn=fake_embed,
        search_fn=fake_search,
        multi_hop_max_rounds=3,
        multi_hop_min_chunks=2,
        multi_hop_min_best_relevance=0.5,
        multi_hop_relax_relevance=False,
        feedback_budget_chars=320,
        messages_for_fallback=None,
    )
    assert len(merged) == 2
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_multi_hop_second_round_when_weak() -> None:
    calls: List[str] = []

    async def fake_embed(q: str) -> List[float]:
        calls.append(q)
        return [0.1] * 8

    weak = [
        {
            "knowledge_base_id": "kb",
            "document_id": "d1",
            "chunk_id": "c1",
            "content": "weak snippet about widgets",
            "relevance_score": 0.35,
        },
    ]
    strong_extra = [
        {
            "knowledge_base_id": "kb",
            "document_id": "d2",
            "chunk_id": "c9",
            "content": "decisive answer about widgets and foobar",
            "relevance_score": 0.92,
        },
    ]
    idx = {"n": 0}

    async def fake_search(_qt: str, _qe: List[float], _eff: float) -> List[Dict[str, Any]]:
        idx["n"] += 1
        if idx["n"] == 1:
            return list(weak)
        return list(weak) + strong_extra

    merged, detail = await run_multi_hop_retrieval(
        initial_query="widgets foobar",
        rerank_top_k=10,
        min_relevance_score=0.3,
        embed_fn=fake_embed,
        search_fn=fake_search,
        multi_hop_max_rounds=3,
        multi_hop_min_chunks=2,
        multi_hop_min_best_relevance=0.6,
        multi_hop_relax_relevance=False,
        feedback_budget_chars=320,
        messages_for_fallback=None,
    )
    assert len(calls) == 2
    assert detail["rounds"] == 2
    assert len(merged) >= 2
