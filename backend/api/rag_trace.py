"""
RAG Trace API
提供 RAG Trace 的内部和外部 API
"""
from fastapi import APIRouter, Body, Request
from typing import List, Literal

from log import logger
from pydantic import BaseModel, ConfigDict

from api.errors import raise_api_error
from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
from core.types import RAGTraceResponse, RAGTraceChunk
from pathlib import Path
from config.settings import settings
from core.utils.user_context import get_user_id

router = APIRouter(prefix="/api/rag", tags=["RAG Trace"])

# 使用默认数据库路径
_db_path = RAGTraceStore.default_db_path()
_trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=_db_path))


class RagTraceStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str


class RagTraceAckResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = True


# =========================
# 内部 API（不对前端暴露）
# =========================

@router.post("/internal/trace/start")
async def start_trace(
    request: Request,
    session_id: str,
    message_id: str,
    rag_id: str,
    rag_type: str = "naive",
    query: str = "",
    embedding_model: str = "",
    vector_store: str = "sqlite-vec",
    top_k: int = 5,
) -> RagTraceStartResponse:
    """
    创建 RAG Trace（内部调用）
    
    ⚠️ 不对前端暴露，仅供后端内部使用
    """
    try:
        user_id = get_user_id(request)
        trace_id = _trace_store.create_trace(
            session_id=session_id,
            message_id=message_id,
            rag_id=rag_id,
            rag_type=rag_type,
            query=query,
            embedding_model=embedding_model,
            vector_store=vector_store,
            top_k=top_k,
            user_id=user_id,
        )
        return RagTraceStartResponse(trace_id=trace_id)
    except Exception as e:
        logger.error(f"Failed to create trace: {e}", exc_info=True)
        raise_api_error(status_code=500, code="rag_trace_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.post("/internal/trace/{trace_id}/chunks")
async def add_trace_chunks(
    trace_id: str,
    chunks: List[RAGTraceChunk] = Body(...),
) -> RagTraceAckResponse:
    """
    追加检索结果 chunks（内部调用）
    
    ⚠️ 不对前端暴露，仅供后端内部使用
    """
    try:
        _trace_store.add_chunks(trace_id, [c.model_dump(mode="json") for c in chunks])
        return RagTraceAckResponse()
    except ValueError as e:
        raise_api_error(status_code=400, code="rag_trace_invalid_chunks", message=str(e), details={"trace_id": trace_id})
        raise AssertionError("unreachable")
    except Exception as e:
        logger.error(f"Failed to add chunks to trace {trace_id}: {e}", exc_info=True)
        raise_api_error(status_code=500, code="rag_trace_internal_error", message=str(e), details={"trace_id": trace_id})
        raise AssertionError("unreachable")


@router.post("/internal/trace/{trace_id}/finalize")
async def finalize_trace(
    trace_id: str,
    injected_token_count: int,
) -> RagTraceAckResponse:
    """
    完成 Trace（推理结束后调用，内部调用）
    
    ⚠️ 不对前端暴露，仅供后端内部使用
    """
    try:
        _trace_store.finalize_trace(trace_id, injected_token_count)
        return RagTraceAckResponse()
    except ValueError as e:
        raise_api_error(status_code=400, code="rag_trace_finalize_invalid", message=str(e), details={"trace_id": trace_id})
        raise AssertionError("unreachable")
    except Exception as e:
        logger.error(f"Failed to finalize trace {trace_id}: {e}", exc_info=True)
        raise_api_error(status_code=500, code="rag_trace_internal_error", message=str(e), details={"trace_id": trace_id})
        raise AssertionError("unreachable")


# =========================
# 外部 API（供前端调用）
# =========================

@router.get("/trace/by-message/{message_id}")
async def get_trace_by_message(message_id: str) -> RAGTraceResponse:
    """
    通过 message_id 获取 RAG Trace（前端调用）
    
    返回格式：
    {
        "rag_used": true/false,
        "trace": {...} 或 null
    }
    """
    try:
        trace_data = _trace_store.get_trace_by_message_id(message_id)
        
        if not trace_data:
            return RAGTraceResponse(rag_used=False, trace=None)
        
        # 转换为 Pydantic 模型
        from core.types import RAGTrace
        trace = RAGTrace(**trace_data)
        
        return RAGTraceResponse(rag_used=True, trace=trace)
    except Exception as e:
        logger.error(f"Failed to get trace for message {message_id}: {e}", exc_info=True)
        raise_api_error(status_code=500, code="rag_trace_internal_error", message=str(e), details={"message_id": message_id})
        raise AssertionError("unreachable")


@router.get("/trace/{trace_id}")
async def get_trace_by_id(trace_id: str) -> RAGTraceResponse:
    """
    通过 trace_id 获取 RAG Trace（前端兜底：当 by-message 查不到时可用 meta.rag.trace_id 查询）
    """
    try:
        trace_data = _trace_store.get_trace_by_id(trace_id)
        if not trace_data:
            return RAGTraceResponse(rag_used=False, trace=None)
        from core.types import RAGTrace
        trace = RAGTrace(**trace_data)
        return RAGTraceResponse(rag_used=True, trace=trace)
    except Exception as e:
        logger.error(f"Failed to get trace by id {trace_id}: {e}", exc_info=True)
        raise_api_error(status_code=500, code="rag_trace_internal_error", message=str(e), details={"trace_id": trace_id})
        raise AssertionError("unreachable")
