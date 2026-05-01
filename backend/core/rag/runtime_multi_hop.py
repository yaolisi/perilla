"""
运行时多跳检索：合并去重、相关性反馈扩展查询、轮次控制。
供 RAG 插件与 Agent RAGRetrieval 共用，避免重复实现。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

ChunkDict = Dict[str, Any]


def chunk_dedup_key(item: ChunkDict) -> str:
    return (
        f'{item.get("knowledge_base_id", "")}::'
        f'{item.get("document_id", "")}::'
        f'{item.get("chunk_id", "")}'
    )


def infer_chunk_score(item: ChunkDict) -> float:
    r = item.get("relevance_score")
    if r is not None:
        return float(r)
    vr = item.get("vector_relevance")
    if vr is not None:
        return float(vr)
    d = float(item.get("distance", 1.0))
    return max(0.0, 1.0 - d)


def merge_chunks_into(merged: Dict[str, ChunkDict], batch: List[ChunkDict]) -> None:
    for item in batch:
        key = chunk_dedup_key(item)
        prev = merged.get(key)
        if prev is None:
            merged[key] = dict(item)
            continue
        if infer_chunk_score(item) >= infer_chunk_score(prev):
            merged[key] = dict(item)


def sorted_chunk_list(merged: Dict[str, ChunkDict]) -> List[ChunkDict]:
    rows = list(merged.values())
    rows.sort(key=infer_chunk_score, reverse=True)
    return rows


def finalize_merged_chunks(merged: Dict[str, ChunkDict], limit: int) -> List[ChunkDict]:
    rows = sorted_chunk_list(merged)
    if limit <= 0:
        return rows
    return rows[:limit]


def need_multi_hop_continue(
    merged: Dict[str, ChunkDict],
    min_chunks: int,
    min_best_relevance: float,
) -> bool:
    if not merged:
        return True
    rows = sorted_chunk_list(merged)
    best = infer_chunk_score(rows[0])
    n = len(merged)
    if min_chunks > 0 and n < min_chunks:
        return True
    if min_best_relevance > 0 and best < min_best_relevance:
        return True
    return False


def expand_query_with_feedback(
    base_query: str,
    merged_chunks_sorted: List[ChunkDict],
    max_total_chars: int,
    snippet_per_chunk: int,
) -> str:
    budget = max(0, max_total_chars - len(base_query) - 24)
    parts: List[str] = []
    used = 0
    for ch in merged_chunks_sorted[:4]:
        snip = (ch.get("content") or "").strip().replace("\n", " ")
        if not snip:
            continue
        piece = snip[:snippet_per_chunk]
        if used + len(piece) > budget:
            piece = piece[: max(0, budget - used)]
        if piece:
            parts.append(piece)
            used += len(piece)
        if used >= budget:
            break
    fb = " ".join(parts).strip()
    if not fb:
        return base_query.strip()
    return f"{base_query.strip()}\n---\n{fb}"[:max_total_chars]


def last_user_message_only(messages: List[Dict[str, Any]], max_length: int = 512) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            c = (msg.get("content") or "").strip()
            if c:
                return c[:max_length]
    return ""


async def run_multi_hop_retrieval(
    *,
    initial_query: str,
    rerank_top_k: int,
    min_relevance_score: float,
    embed_fn: Callable[[str], Awaitable[List[float]]],
    search_fn: Callable[[str, List[float], float], Awaitable[List[ChunkDict]]],
    multi_hop_max_rounds: int,
    multi_hop_min_chunks: int,
    multi_hop_min_best_relevance: float,
    multi_hop_relax_relevance: bool,
    feedback_budget_chars: int,
    messages_for_fallback: Optional[List[Dict[str, Any]]],
) -> Tuple[List[ChunkDict], Dict[str, Any]]:
    merged: Dict[str, ChunkDict] = {}
    queries: List[str] = []
    base_query = (initial_query or "").strip()
    current_query = base_query

    for hop in range(multi_hop_max_rounds):
        eff_min = float(min_relevance_score)
        if multi_hop_relax_relevance and hop > 0:
            eff_min = max(0.05, float(min_relevance_score) * (0.88 ** hop))

        queries.append(current_query)
        qemb = await embed_fn(current_query)
        round_chunks = await search_fn(current_query, qemb, eff_min)
        merge_chunks_into(merged, round_chunks)

        if hop >= multi_hop_max_rounds - 1:
            break
        if not need_multi_hop_continue(merged, multi_hop_min_chunks, multi_hop_min_best_relevance):
            break

        sm = sorted_chunk_list(merged)
        if sm:
            current_query = expand_query_with_feedback(
                base_query=base_query,
                merged_chunks_sorted=sm,
                max_total_chars=min(2048, len(base_query) + feedback_budget_chars),
                snippet_per_chunk=min(220, max(80, feedback_budget_chars // 2)),
            )
        else:
            fb = last_user_message_only(messages_for_fallback or [], max_length=512)
            if fb and fb.strip() != base_query.strip():
                current_query = fb.strip()
            else:
                break

    final_list = finalize_merged_chunks(merged, rerank_top_k)
    detail = {"rounds": len(queries), "queries": queries}
    return final_list, detail
