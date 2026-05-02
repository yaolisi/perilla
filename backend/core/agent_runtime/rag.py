"""
RAG Context Retrieval for Agent Runtime
Retrieves relevant context from knowledge bases for agent execution
"""
from typing import List, Dict, Any, Optional

from log import logger
from core.knowledge.knowledge_base_store import (
    DEFAULT_KB_TENANT_ID,
    KnowledgeBaseStore,
    KnowledgeBaseConfig,
)
from core.utils.user_context import ResourceNotFoundError, UserAccessDeniedError
from core.rag.runtime_multi_hop import run_multi_hop_retrieval
from config.settings import settings

# Global KB store instance
_kb_store: Optional[KnowledgeBaseStore] = None

def get_kb_store() -> KnowledgeBaseStore:
    """Get or create the knowledge base store singleton"""
    global _kb_store
    if _kb_store is None:
        try:
            from pathlib import Path
            if settings.db_path:
                db_path = Path(settings.db_path)
            else:
                # Use default path consistent with other stores
                root = Path(__file__).resolve().parents[2]
                db_path = root / "data" / "platform.db"
            _kb_store = KnowledgeBaseStore(
                KnowledgeBaseConfig(
                    db_path=db_path,
                    embedding_dim=settings.memory_embedding_dim
                )
            )
            logger.info("[RAGRetrieval] KnowledgeBaseStore initialized")
        except Exception as e:
            logger.warning(f"[RAGRetrieval] Failed to initialize KnowledgeBaseStore: {e}")
            _kb_store = None
    return _kb_store


class RAGRetrieval:
    """
    RAG Context Retrieval Helper
    
    Provides methods to retrieve relevant context from knowledge bases
    for agent execution.
    """
    
    def __init__(self):
        self.kb_store = get_kb_store()
    
    async def retrieve_context(
        self,
        query: str,
        knowledge_base_ids: List[str],
        top_k: int = 5,
        max_distance: Optional[float] = None,
        retrieval_mode: str = "hybrid",
        min_relevance_score: float = 0.5,
        *,
        rag_multi_hop_enabled: bool = False,
        multi_hop_max_rounds: int = 3,
        multi_hop_min_chunks: int = 2,
        multi_hop_min_best_relevance: float = 0.0,
        multi_hop_relax_relevance: bool = True,
        multi_hop_feedback_chars: int = 320,
        fallback_messages: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        Retrieve relevant context from knowledge bases
        
        Args:
            query: The query to search for
            knowledge_base_ids: List of knowledge base IDs to search in
            top_k: Number of results to return（hybrid 时为 rerank 后保留条数）
            max_distance: 向量距离上限（与 RAG 插件 score_threshold 语义一致；默认 1.2）
            retrieval_mode: vector | hybrid（默认 hybrid：关键词 + 向量 + 轻量重排）
            min_relevance_score: hybrid 模式下 rerank 阈值
            rag_multi_hop_enabled: 是否启用与 Chat RAG 插件一致的多轮合并检索
            multi_hop_*: 多跳参数（与 RAG 插件默认/范围对齐）
            fallback_messages: 多跳无 chunk 时用于回退的最后用户句（role/content 字典列表）
            
        Returns:
            Formatted context string for the agent
        """
        if not knowledge_base_ids:
            return ""
            
        if not self.kb_store:
            logger.warning("[RAGRetrieval] KB store not available")
            return ""
        
        try:
            # Check if vector search is available
            if not getattr(self.kb_store, '_vec_available', False):
                logger.debug("[RAGRetrieval] sqlite-vec not available, skipping RAG")
                return ""

            uid = (user_id or "default").strip() or "default"
            tid = (tenant_id or DEFAULT_KB_TENANT_ID).strip() or DEFAULT_KB_TENANT_ID
            kb_infos: List[tuple[str, Dict[str, Any]]] = []
            for kb_id in knowledge_base_ids:
                try:
                    info = self.kb_store.get_knowledge_base(
                        kb_id, user_id=uid, tenant_id=tid
                    )
                except (ResourceNotFoundError, UserAccessDeniedError):
                    info = None
                if info:
                    kb_infos.append((kb_id, info))
            if not kb_infos:
                logger.debug("[RAGRetrieval] No valid knowledge bases for ids=%s", knowledge_base_ids)
                return ""

            embed_ids = {row[1].get("embedding_model_id") for row in kb_infos if row[1].get("embedding_model_id")}
            if len(embed_ids) > 1:
                logger.warning(
                    "[RAGRetrieval] Multiple embedding models across KBs: %s; using first KB model",
                    embed_ids,
                )
            embedding_model_id = str(kb_infos[0][1].get("embedding_model_id") or "").strip()
            if not embedding_model_id:
                logger.warning("[RAGRetrieval] Missing embedding_model_id on knowledge base")
                return ""

            eff_distance = float(max_distance if max_distance is not None else 1.2)
            mode = (retrieval_mode or "hybrid").strip().lower()
            keyword_limit = max(top_k * 4, 20)
            vector_limit = max(top_k * 4, 20)
            rerank_limit = max(top_k, 1)

            mh_rounds = max(2, min(5, int(multi_hop_max_rounds)))
            mh_min_chunks = max(0, min(50, int(multi_hop_min_chunks)))
            mh_min_best = max(0.0, min(1.0, float(multi_hop_min_best_relevance)))
            mh_fb = max(80, min(2000, int(multi_hop_feedback_chars)))

            async def _embed_one(q: str) -> List[float]:
                emb = await self._embed_query_gateway(q, embedding_model_id)
                if not emb:
                    raise RuntimeError("empty embedding")
                return emb

            async def _search_one(qt: str, qemb: List[float], eff_min: float) -> List[Dict[str, Any]]:
                if mode == "hybrid":
                    return self.kb_store.hybrid_search_chunks_multi_kb(
                        knowledge_base_ids=knowledge_base_ids,
                        query_text=qt,
                        query_embedding=qemb,
                        keyword_limit=keyword_limit,
                        vector_limit=vector_limit,
                        rerank_limit=rerank_limit,
                        min_relevance_score=float(eff_min),
                        max_distance=eff_distance,
                        version_id=None,
                    )
                return self.kb_store.search_chunks_multi_kb(
                    knowledge_base_ids=knowledge_base_ids,
                    query_embedding=qemb,
                    limit=top_k,
                    max_distance=eff_distance,
                    version_id=None,
                )

            if rag_multi_hop_enabled:
                results, mh_detail = await run_multi_hop_retrieval(
                    initial_query=query,
                    rerank_top_k=rerank_limit,
                    min_relevance_score=float(min_relevance_score),
                    embed_fn=_embed_one,
                    search_fn=_search_one,
                    multi_hop_max_rounds=mh_rounds,
                    multi_hop_min_chunks=mh_min_chunks,
                    multi_hop_min_best_relevance=mh_min_best,
                    multi_hop_relax_relevance=bool(multi_hop_relax_relevance),
                    feedback_budget_chars=mh_fb,
                    messages_for_fallback=fallback_messages,
                )
                logger.info(
                    "[RAGRetrieval] Multi-hop retrieval rounds=%s queries=%s",
                    mh_detail.get("rounds"),
                    len(mh_detail.get("queries") or []),
                )
            else:
                query_embedding = await self._embed_query_gateway(query, embedding_model_id)
                if not query_embedding:
                    logger.warning("[RAGRetrieval] Failed to generate query embedding via gateway")
                    return ""
                if mode == "hybrid":
                    results = self.kb_store.hybrid_search_chunks_multi_kb(
                        knowledge_base_ids=knowledge_base_ids,
                        query_text=query,
                        query_embedding=query_embedding,
                        keyword_limit=keyword_limit,
                        vector_limit=vector_limit,
                        rerank_limit=rerank_limit,
                        min_relevance_score=float(min_relevance_score),
                        max_distance=eff_distance,
                        version_id=None,
                    )
                else:
                    results = self.kb_store.search_chunks_multi_kb(
                        knowledge_base_ids=knowledge_base_ids,
                        query_embedding=query_embedding,
                        limit=top_k,
                        max_distance=eff_distance,
                        version_id=None,
                    )
            
            if not results:
                logger.debug(f"[RAGRetrieval] No results found for query")
                return ""
            
            # Format results as context
            context_parts = [f"Retrieved Context (from {len(results)} sources):"]
            for i, result in enumerate(results, 1):
                source = result.get('doc_source', 'Unknown')
                content = result.get('content', '')
                distance = float(result.get('distance', 0) or 0)
                rel = result.get("relevance_score")
                rel_s = f"{float(rel):.2f}" if rel is not None else f"{max(0.0, 1.0 - distance):.2f}"
                
                context_parts.append(f"\n--- Source {i} ({source}, relevance: {rel_s}) ---")
                context_parts.append(content[:1000])  # Limit content length
            
            context = '\n'.join(context_parts)
            logger.info(f"[RAGRetrieval] Retrieved {len(results)} chunks for query")
            
            return context
            
        except Exception as e:
            logger.error(f"[RAGRetrieval] Error retrieving context: {e}")
            return ""
    
    async def _embed_query_gateway(self, query: str, embedding_model_id: str) -> Optional[List[float]]:
        """通过推理网关生成查询向量（与 RAG 插件一致，保证与知识库写入维度一致）。"""
        try:
            from core.models.registry import get_model_registry
            from core.inference import get_inference_client

            model = get_model_registry().get_model(embedding_model_id)
            if not model:
                return None
            client = get_inference_client()
            resp = await client.embed(
                model=model.id,
                input_text=[query],
                metadata={
                    "caller": "agent_runtime.RAGRetrieval.embed_query",
                    "embedding_model_id": embedding_model_id,
                },
            )
            rows = resp.embeddings
            if not rows:
                return None
            return rows[0]
        except Exception as e:
            logger.warning("[RAGRetrieval] Gateway embed failed: %s", str(e)[:200])
            return None

    async def get_knowledge_base_info(
        self,
        kb_id: str,
        *,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get information about a specific knowledge base"""
        if not self.kb_store:
            return None

        uid = (user_id or "default").strip() or "default"
        tid = (tenant_id or DEFAULT_KB_TENANT_ID).strip() or DEFAULT_KB_TENANT_ID
        try:
            return self.kb_store.get_knowledge_base(kb_id, user_id=uid, tenant_id=tid)
        except Exception as e:
            logger.error(f"[RAGRetrieval] Error getting KB info: {e}")
            return None


# Global retrieval instance
_rag_retrieval: Optional[RAGRetrieval] = None

def get_rag_retrieval() -> RAGRetrieval:
    """Get or create the RAG retrieval singleton"""
    global _rag_retrieval
    if _rag_retrieval is None:
        _rag_retrieval = RAGRetrieval()
    return _rag_retrieval
