"""
RAG Plugin v1
实现 retrieve → inject → merge 完整流程
"""
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.plugins.base import Plugin
from core.rag.runtime_multi_hop import run_multi_hop_retrieval
from core.plugins.context import PluginContext
from core.knowledge.knowledge_base_store import DEFAULT_KB_TENANT_ID
from core.utils.user_context import ResourceNotFoundError, UserAccessDeniedError
from core.types import Message
from log import logger


class RAGPlugin(Plugin):
    """
    RAG (Retrieval-Augmented Generation) 插件 v1
    
    职责：
    1. retrieve: 调用 embedding runtime + sqlite-vec
    2. inject: 构造 context prompt
    3. merge: 和用户 messages 合并
    
    架构位置：
    Chat Request → RAG Plugin → Unified Agent → LLM Runtime
    """
    name = "rag"
    version = "1.0.0"
    description = "Retrieval-Augmented Generation: retrieve context from knowledge base and inject into messages"
    type = "capability"
    stage = "pre"  # 在模型推理前执行，用于增强上下文

    supported_modes = ["chat", "agent"]
    permissions = []  # RAG 不需要特殊权限

    input_schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["role", "content"],
                },
                "description": "聊天消息列表",
            },
            "rag": {
                "type": "object",
                "properties": {
                    "knowledge_base_id": {"type": "string"},
                    "knowledge_base_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选，支持多个知识库同时检索"
                    },
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                    "retrieval_mode": {
                        "type": "string",
                        "default": "hybrid",
                        "enum": ["vector", "hybrid"],
                        "description": "检索模式：vector=纯向量，hybrid=关键词+向量+重排序"
                    },
                    "keyword_top_k": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "vector_top_k": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                    "rerank_top_k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                    "min_relevance_score": {"type": "number", "default": 0.5, "minimum": 0, "maximum": 1},
                    "version_id": {"type": "string"},
                    "version_label": {"type": "string"},
                    # 注意：score_threshold 实际是 distance 阈值（max_distance）
                    # embedding 默认 L2 normalize，常见距离范围约 0~2
                    "score_threshold": {"type": "number", "default": 1.2, "minimum": 0, "maximum": 2},
                    "multi_hop_enabled": {
                        "type": "boolean",
                        "default": False,
                        "description": "启用运行时多跳：首轮不足时基于相关性反馈扩展查询再检索并合并去重",
                    },
                    "multi_hop_max_rounds": {
                        "type": "integer",
                        "default": 3,
                        "minimum": 2,
                        "maximum": 5,
                        "description": "多跳检索最大轮数（含首轮）",
                    },
                    "multi_hop_min_chunks": {
                        "type": "integer",
                        "default": 2,
                        "minimum": 0,
                        "maximum": 50,
                        "description": "合并后 chunk 数低于该值则尝试下一轮；0 表示不按数量触发",
                    },
                    "multi_hop_min_best_relevance": {
                        "type": "number",
                        "default": 0.0,
                        "minimum": 0,
                        "maximum": 1,
                        "description": "最佳 relevance_score 低于该值则尝试下一轮；0 表示不按分数触发",
                    },
                    "multi_hop_relax_relevance": {
                        "type": "boolean",
                        "default": True,
                        "description": "第二轮及以后将 min_relevance_score 按轮次温和放宽，减轻冷启动",
                    },
                    "multi_hop_feedback_chars": {
                        "type": "integer",
                        "default": 320,
                        "minimum": 80,
                        "maximum": 2000,
                        "description": "相关性反馈拼接时从高分 chunk 抽取的最大总字符数",
                    },
                },
                # 取消 knowledge_base_id 的硬性要求，改为在代码中判断两者其一
            },
        },
        "required": ["messages", "rag"],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "retrieved_chunks": {"type": "integer"},
                    "sources": {"type": "array", "items": {"type": "string"}}
                }
            }
        },
        "required": ["messages"],
    }

    async def initialize(self, context: PluginContext) -> bool:
        """
        初始化插件
        
        注意：knowledge_base_store 和 runtime_factory 在初始化时可能不可用，
        它们会在执行时通过 PluginContext 提供，所以这里不强制要求。
        """
        # 调用父类方法设置 _initialized 标志
        result = await super().initialize(context)
        if not result:
            return False
        
        # 插件初始化时这些依赖可能还未准备好，但在执行时会提供
        # 所以这里只记录警告，不阻止注册
        if context.knowledge_base_store is None:
            logger.debug("[RAGPlugin] KnowledgeBaseStore not available during initialization (will be provided at runtime)")
        
        if context.runtime_factory is None:
            logger.debug("[RAGPlugin] RuntimeFactory not available during initialization (will be provided at runtime)")
        
        # 允许插件注册，即使依赖在初始化时不可用
        return True

    async def execute(
        self,
        input: Dict[str, Any],
        context: PluginContext,
    ) -> Dict[str, Any]:
        """
        执行 RAG 流程：retrieve → inject → merge
        
        注意：在执行时检查依赖是否可用
        """
        # 在执行时检查依赖
        if context.knowledge_base_store is None:
            if context.logger:
                context.logger.error("[RAGPlugin] KnowledgeBaseStore not available in context")
            return {"messages": input.get("messages", [])}
        
        if context.runtime_factory is None:
            if context.logger:
                context.logger.error("[RAGPlugin] RuntimeFactory not available in context")
            return {"messages": input.get("messages", [])}
        
        messages: List[Dict[str, Any]] = input["messages"]
        rag_config: Dict[str, Any] = input["rag"]
        
        # 获取 KB IDs，优先支持多选，向后兼容单选
        kb_ids = rag_config.get("knowledge_base_ids") or []
        kb_id = rag_config.get("knowledge_base_id")
        if kb_id and kb_id not in kb_ids:
            kb_ids.append(kb_id)
            
        if not kb_ids:
            if context.logger:
                context.logger.warning("[RAGPlugin] No knowledge_base_id or knowledge_base_ids provided")
            return {"messages": messages}

        top_k = rag_config.get("top_k", 5)
        retrieval_mode = rag_config.get("retrieval_mode", "hybrid")
        keyword_top_k = rag_config.get("keyword_top_k", max(top_k * 2, 10))
        vector_top_k = rag_config.get("vector_top_k", max(top_k * 2, 10))
        rerank_top_k = rag_config.get("rerank_top_k", top_k)
        min_relevance_score = float(rag_config.get("min_relevance_score", 0.5))
        version_id = rag_config.get("version_id")
        version_label = rag_config.get("version_label")
        if not version_id and version_label and kb_ids:
            version_id = context.knowledge_base_store.resolve_kb_version_id(
                kb_id=kb_ids[0],
                version_label=version_label,
            )
        score_threshold = rag_config.get("score_threshold", 1.2)
        multi_hop_enabled = bool(rag_config.get("multi_hop_enabled", False))
        multi_hop_max_rounds = int(rag_config.get("multi_hop_max_rounds", 3))
        multi_hop_max_rounds = max(2, min(5, multi_hop_max_rounds))
        multi_hop_min_chunks = int(rag_config.get("multi_hop_min_chunks", 2))
        multi_hop_min_chunks = max(0, min(50, multi_hop_min_chunks))
        multi_hop_min_best_relevance = float(rag_config.get("multi_hop_min_best_relevance", 0.0))
        multi_hop_min_best_relevance = max(0.0, min(1.0, multi_hop_min_best_relevance))
        multi_hop_relax_relevance = bool(rag_config.get("multi_hop_relax_relevance", True))
        multi_hop_feedback_chars = int(rag_config.get("multi_hop_feedback_chars", 320))
        multi_hop_feedback_chars = max(80, min(2000, multi_hop_feedback_chars))

        if context.logger:
            context.logger.info(
                f"[RAGPlugin] Processing RAG request: kb_ids={kb_ids}, top_k={top_k}, "
                f"mode={retrieval_mode}, score_threshold={score_threshold}"
            )

        # 1. Context-Aware Query Extraction: 结合上下文生成检索 Query
        # 简单策略：结合最后两个回合的消息，帮助解决指代消解问题
        # 限制长度避免超出 embedding 模型的 token 限制
        query_text = self._extract_context_aware_query(messages, max_length=512)
        if not query_text:
            if context.logger:
                context.logger.warning("[RAGPlugin] No query text extracted, skipping RAG")
            return {"messages": messages}

        # 2. Retrieve: 验证所有知识库使用相同的 embedding 模型
        embedding_model_ids = set()
        kb_infos = {}
        for kb_id in kb_ids:
            uid = context.user_id or "default"
            tid = (context.tenant_id or DEFAULT_KB_TENANT_ID).strip() or DEFAULT_KB_TENANT_ID
            try:
                kb_info = context.knowledge_base_store.get_knowledge_base(
                    kb_id, user_id=uid, tenant_id=tid
                )
            except (ResourceNotFoundError, UserAccessDeniedError):
                kb_info = None
            if not kb_info:
                if context.logger:
                    context.logger.warning(
                        f"[RAGPlugin] Knowledge base '{kb_id}' not found or access denied, skipping"
                    )
                continue
            kb_infos[kb_id] = kb_info
            embedding_model_ids.add(kb_info["embedding_model_id"])
        
        if not kb_infos:
            if context.logger:
                context.logger.error(f"[RAGPlugin] No valid knowledge bases found")
            return {"messages": messages}
        
        # 检查 embedding 模型一致性
        if len(embedding_model_ids) > 1:
            if context.logger:
                context.logger.warning(
                    f"[RAGPlugin] Multiple embedding models detected: {embedding_model_ids}. "
                    f"Using first model '{list(embedding_model_ids)[0]}' for query embedding. "
                    f"This may cause dimension mismatch issues."
                )
        
        # 使用第一个知识库的 embedding 模型
        target_kb_id = list(kb_infos.keys())[0]
        embedding_model_id = kb_infos[target_kb_id]["embedding_model_id"]
        
        if not context.registry:
            return {"messages": messages}
        
        embedding_model = context.registry.get_model(embedding_model_id)
        if not embedding_model:
            return {"messages": messages}

        # 生成 query embedding（通过 Inference Gateway 解耦调用方）
        try:
            from core.inference import get_inference_client
            client = get_inference_client()

            async def _embed_one(q: str) -> List[float]:
                resp = await client.embed(
                    model=embedding_model.id,
                    input_text=[q],
                    metadata={
                        "caller": "RAGPlugin.embed_query",
                        "session_id": context.session_id or "",
                        "agent_id": context.agent_id or "",
                        "kb_ids": kb_ids,
                    },
                )
                rows = resp.embeddings
                if not rows:
                    raise RuntimeError("empty embeddings")
                return rows[0]

            async def _search_one(qt: str, qemb: List[float], eff_min: float) -> List[Dict[str, Any]]:
                if retrieval_mode == "hybrid":
                    return context.knowledge_base_store.hybrid_search_chunks_multi_kb(
                        knowledge_base_ids=kb_ids,
                        query_text=qt,
                        query_embedding=qemb,
                        keyword_limit=keyword_top_k,
                        vector_limit=vector_top_k,
                        rerank_limit=rerank_top_k,
                        min_relevance_score=eff_min,
                        max_distance=score_threshold,
                        version_id=version_id,
                    )
                return context.knowledge_base_store.search_chunks_multi_kb(
                    knowledge_base_ids=kb_ids,
                    query_embedding=qemb,
                    limit=top_k,
                    max_distance=score_threshold,
                    version_id=version_id,
                )

            chunks = []
            mh_detail: Dict[str, Any] = {}
            try:
                if multi_hop_enabled:
                    chunks, mh_detail = await run_multi_hop_retrieval(
                        initial_query=query_text,
                        rerank_top_k=rerank_top_k,
                        min_relevance_score=min_relevance_score,
                        embed_fn=_embed_one,
                        search_fn=_search_one,
                        multi_hop_max_rounds=multi_hop_max_rounds,
                        multi_hop_min_chunks=multi_hop_min_chunks,
                        multi_hop_min_best_relevance=multi_hop_min_best_relevance,
                        multi_hop_relax_relevance=multi_hop_relax_relevance,
                        feedback_budget_chars=multi_hop_feedback_chars,
                        messages_for_fallback=messages,
                    )
                else:
                    qemb = await _embed_one(query_text)
                    chunks = await _search_one(query_text, qemb, min_relevance_score)
            except Exception as e:
                if context.logger:
                    context.logger.error(f"[RAGPlugin] Vector search failed: {e}")
                trace_id = self._record_trace_retrieve(
                    context=context,
                    query_text=query_text,
                    embedding_model_id=embedding_model_id,
                    kb_ids=kb_ids,
                    top_k=top_k,
                    chunks=[],
                )
                return {
                    "messages": messages,
                    "metadata": {
                        "retrieved_chunks": 0,
                        "sources": [],
                        "trace_id": trace_id,
                    },
                }

        except Exception as e:
            if context.logger:
                context.logger.error(f"[RAGPlugin] Failed to embed query: {e}")
            return {"messages": messages}

        trace_query = query_text
        trace_type = "multi_hop" if multi_hop_enabled else "naive"
        if multi_hop_enabled and mh_detail.get("queries"):
            trace_query = "[multi_hop] " + " | ".join(mh_detail["queries"])[:4000]

        # RAG Trace: 记录检索结果（无论是否找到 chunks）
        trace_id = self._record_trace_retrieve(
            context=context,
            query_text=trace_query,
            embedding_model_id=embedding_model_id,
            kb_ids=kb_ids,
            top_k=top_k,
            chunks=chunks,
            version_id=version_id,
            rag_type_override=trace_type,
        )

        if not chunks:
            if context.logger:
                context.logger.info("[RAGPlugin] No relevant chunks found")
            empty_meta: Dict[str, Any] = {
                "retrieved_chunks": 0,
                "sources": [],
                "trace_id": trace_id,
            }
            if multi_hop_enabled and mh_detail:
                empty_meta["multi_hop"] = {
                    "rounds": mh_detail.get("rounds"),
                    "queries": mh_detail.get("queries"),
                }
            return {"messages": messages, "metadata": empty_meta}

        # 3. Inject: 构造 context prompt (含引用)
        # 获取模型的上下文长度（如果可用），默认使用 2000 tokens 作为 RAG 上下文预算
        # 注意：这里需要从 input 中获取模型信息，或者从 context 中获取
        # 为了安全，我们使用保守的默认值，并允许通过配置调整
        max_context_tokens = rag_config.get("max_context_tokens", 2000)
        context_text = self._build_context(chunks, max_context_tokens=max_context_tokens)
        graph_context = self._build_graph_context(
            context=context,
            kb_ids=kb_ids,
            query_text=query_text,
            top_k=3,
            version_id=version_id,
        )
        if graph_context:
            context_text = f"{context_text}\n\nKnowledge Graph Facts:\n{graph_context}" if context_text else graph_context

        # 4. Merge: 合并到 messages (优化合并策略)
        enhanced_messages = self._merge_context(messages, context_text)

        sources = sorted(list(set([c.get("doc_source", "Unknown") for c in chunks])))
        
        if context.logger:
            context.logger.info(
                f"[RAGPlugin] RAG completed: retrieved {len(chunks)} chunks from {len(sources)} sources"
            )

        meta: Dict[str, Any] = {
            "retrieved_chunks": len(chunks),
            "sources": sources,
            "trace_id": trace_id,
        }
        if multi_hop_enabled and mh_detail:
            meta["multi_hop"] = {
                "rounds": mh_detail.get("rounds"),
                "queries": mh_detail.get("queries"),
            }

        return {
            "messages": enhanced_messages,
            "metadata": meta,
        }

    def _build_graph_context(
        self,
        context: PluginContext,
        kb_ids: List[str],
        query_text: str,
        top_k: int = 3,
        version_id: Optional[str] = None,
    ) -> str:
        facts: List[str] = []
        for kb_id in kb_ids:
            try:
                rows = context.knowledge_base_store.search_graph_relations(
                    kb_id=kb_id,
                    query_text=query_text,
                    limit=top_k,
                    version_id=version_id,
                )
                for row in rows:
                    s = row.get("source_entity", "")
                    r = row.get("relation", "")
                    t = row.get("target_entity", "")
                    if s and r and t:
                        facts.append(f"- {s} {r} {t}")
            except Exception:
                continue
        if not facts:
            return ""
        return "\n".join(facts[:top_k])

    def _extract_context_aware_query(self, messages: List[Dict[str, Any]], max_length: int = 512) -> str:
        """
        提取具有上下文意识的 Query
        简单版本：拼接最后 User + Assistant + User 消息，提高语义覆盖
        
        Args:
            messages: 消息列表
            max_length: 最大字符长度限制（避免超出 embedding 模型 token 限制）
        """
        recent_messages = []
        count = 0
        for msg in reversed(messages):
            if msg.get("role") in ["user", "assistant"]:
                content = msg.get("content", "").strip()
                if content:
                    recent_messages.append(content)
                    count += 1
            if count >= 3:  # 取最近 3 条消息
                break
        
        if not recent_messages:
            return ""
            
        # 逆序回来
        recent_messages.reverse()
        query_text = "\n".join(recent_messages).strip()
        
        # 如果查询文本太长，只保留最后一条用户消息
        if len(query_text) > max_length:
            # 只使用最后一条用户消息
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "").strip()
                    if content:
                        # 如果最后一条用户消息也很长，截断它
                        return content[:max_length]
        
        return query_text

    def _build_context(self, chunks: List[Dict[str, Any]], max_context_tokens: int = 2000) -> str:
        """
        构造包含引用信息的 context prompt
        
        格式：
        [1] source_filename: content
        [2] source_filename: content
        
        Args:
            chunks: 检索到的 chunks
            max_context_tokens: 最大上下文 token 数（粗略估算：1 token ≈ 4 chars）
        """
        if not chunks:
            return ""

        # 估算 token 数（粗略：1 token ≈ 4 chars）
        max_chars = max_context_tokens * 4
        
        context_parts = []
        total_chars = 0
        prompt_header = (
            "You are a helpful assistant. Use the following context to answer the user's question.\n"
            "If the context doesn't contain the answer, you can still use your own knowledge but prioritize the context provided.\n\n"
            "Context:\n"
            "----------\n"
        )
        prompt_footer = "\n----------\n"
        header_footer_chars = len(prompt_header) + len(prompt_footer)
        
        # 预留一些空间给 header 和 footer
        available_chars = max_chars - header_footer_chars
        
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("doc_source", "Unknown")
            content = chunk.get("content", "").strip()
            if not content:
                continue
            
            # 格式化 chunk
            chunk_text = f"[{i}] {source}:\n{content}"
            chunk_chars = len(chunk_text)
            
            # 如果加上这个 chunk 会超出限制，截断当前 chunk 的内容
            if total_chars + chunk_chars > available_chars:
                remaining_chars = available_chars - total_chars - len(f"[{i}] {source}:\n")
                if remaining_chars > 50:  # 至少保留 50 个字符
                    truncated_content = content[:remaining_chars] + "..."
                    context_parts.append(f"[{i}] {source}:\n{truncated_content}")
                break
            
            context_parts.append(chunk_text)
            total_chars += chunk_chars
        
        if not context_parts:
            return ""
        
        context_text = "\n\n".join(context_parts)
        
        prompt = prompt_header + context_text + prompt_footer
        return prompt

    def _merge_context(self, messages: List[Dict[str, Any]], context_text: str) -> List[Dict[str, Any]]:
        """
        优化合并策略：
        1. 如果已有 system 消息，合并到第一个 system 消息中
        2. 如果没有 system 消息，在最后一条用户消息前插入
        3. 避免产生多个 system 消息（某些模型可能只处理第一个）
        """
        if not messages:
            return [{"role": "system", "content": context_text}]

        enhanced = []
        system_found = False
        
        # 第一遍：查找并合并到第一个 system 消息
        for msg in messages:
            if msg.get("role") == "system" and not system_found:
                # 合并到第一个 system 消息
                original_content = msg.get("content", "").strip()
                if original_content:
                    # 如果已有内容，添加分隔符
                    msg = {
                        "role": "system",
                        "content": f"{original_content}\n\n{context_text}"
                    }
                else:
                    msg = {
                        "role": "system",
                        "content": context_text
                    }
                system_found = True
            enhanced.append(msg)
        
        # 如果没有 system 消息，在最后一条用户消息前插入
        if not system_found:
            last_user_idx = -1
            for i, msg in enumerate(enhanced):
                if msg.get("role") == "user":
                    last_user_idx = i
            
            if last_user_idx >= 0:
                # 插入在最后一条用户消息之前
                enhanced.insert(last_user_idx, {"role": "system", "content": context_text})
            else:
                # 没有用户消息，加在开头
                enhanced.insert(0, {"role": "system", "content": context_text})
        
        return enhanced
    
    def _record_trace_retrieve(
        self,
        context: PluginContext,
        query_text: str,
        embedding_model_id: str,
        kb_ids: List[str],
        top_k: int,
        chunks: List[Dict[str, Any]],
        version_id: Optional[str] = None,
        rag_type_override: Optional[str] = None,
    ) -> Optional[str]:
        """
        记录 RAG Trace 的检索阶段
        
        Returns:
            trace_id 或 None（如果记录失败）
        """
        try:
            # 获取 session_id 和 message_id（从 context 中获取）
            session_id = getattr(context, "session_id", None)
            message_id = getattr(context, "message_id", None)
            
            if not session_id or not message_id:
                if context.logger:
                    context.logger.debug("[RAGPlugin] Missing session_id or message_id, skipping trace")
                return None
            
            # 直接调用 trace_store（避免 HTTP 调用）
            from core.rag.trace_store import RAGTraceStore, RAGTraceStoreConfig
            
            trace_store = RAGTraceStore(RAGTraceStoreConfig(db_path=RAGTraceStore.default_db_path()))
            
            # 获取用户 ID（多用户架构）
            user_id = context.user_id or "default"
            tid = (context.tenant_id or DEFAULT_KB_TENANT_ID).strip() or DEFAULT_KB_TENANT_ID
            
            # 创建 trace
            rag_id = ",".join(kb_ids)  # 多个 KB 用逗号连接
            trace_id = trace_store.create_trace(
                session_id=session_id,
                message_id=message_id,
                rag_id=rag_id,
                rag_type=(rag_type_override or "naive"),
                query=query_text,
                embedding_model=embedding_model_id,
                vector_store="sqlite-vec",
                top_k=top_k,
                user_id=user_id,
                tenant_id=tid,
                version_id=version_id,
            )
            
            # 添加 chunks
            trace_chunks = []
            for rank, chunk in enumerate(chunks, 1):
                trace_chunks.append({
                    "doc_id": chunk.get("document_id"),
                    "doc_name": chunk.get("doc_source"),
                    "chunk_id": chunk.get("chunk_id"),
                    "score": 1.0 - chunk.get("distance", 1.0),  # 转换为相似度分数
                    "content": chunk.get("content", ""),
                    "rank": rank,
                })
            
            if trace_chunks:
                trace_store.add_chunks(trace_id, trace_chunks)
            
            return trace_id
        except Exception as e:
            # Trace 记录失败不应该影响 RAG 流程
            if context.logger:
                context.logger.debug(f"[RAGPlugin] Failed to record trace: {e}")
            return None
