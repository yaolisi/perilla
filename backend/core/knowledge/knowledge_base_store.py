"""
Knowledge Base Store v1
使用 sqlite-vec 实现 RAG 知识库的向量存储和检索
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from log import logger
from config.settings import settings
from core.knowledge.status import KnowledgeBaseStatus, DocumentStatus
from core.data.vector_search import get_vector_provider
from core.utils.user_context import UserAccessDeniedError, ResourceNotFoundError
from core.knowledge.vector_index_snapshot import get_kb_vector_snapshot_store

# 统一单表：业务表与向量表名（阶段 4.3）
UNIFIED_CHUNKS_TABLE = "embedding_chunks"
UNIFIED_VEC_TABLE = "kb_chunks_vec"

# 与 MemoryStore / HistoryStore 一致：未携带租户上下文时使用 default
DEFAULT_KB_TENANT_ID = "default"

# 与旧版 per-KB 向量表名兼容：仅字母数字、点、连字符、下划线；否则用哈希后缀，避免标识符注入。
_KB_ID_SAFE_FOR_TABLE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _chunk_table_suffix_for_kb_id(kb_id: str) -> str:
    raw = kb_id.strip()
    if not raw:
        return hashlib.sha256(b"").hexdigest()[:32]
    if _KB_ID_SAFE_FOR_TABLE_NAME.fullmatch(raw):
        return raw.replace("-", "_").replace(".", "_")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass
class KnowledgeBaseConfig:
    """Knowledge Base 配置"""
    db_path: Path
    embedding_dim: int = 512  # 默认 512 维，需要与 embedding model 一致（可动态更新）


class KnowledgeBaseStore:
    """
    Knowledge Base Store v1
    
    表结构：
    - knowledge_base: RAG 实体
    - document: 原始文档
    - embedding_chunk: 向量 + chunk (sqlite-vec)
    """

    def __init__(self, config: KnowledgeBaseConfig):
        self.config = config
        self._vec_available = False
        self._snapshot_store = get_kb_vector_snapshot_store()
        self._ensure_db()

    @staticmethod
    def default_db_path() -> Path:
        """
        返回默认数据库路径
        
        注意：系统统一使用 platform.db 存储所有数据。
        """
        root = Path(__file__).resolve().parents[3]
        data_dir = root / "backend" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "platform.db"

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接"""
        self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.config.db_path))
        conn.row_factory = sqlite3.Row
        
        # 如果 sqlite-vec 可用，每次连接时都需要加载扩展
        if self._vec_available:
            try:
                conn.enable_load_extension(True)
                try:
                    import sqlite_vec  # type: ignore
                    sqlite_vec.load(conn)  # type: ignore
                finally:
                    conn.enable_load_extension(False)
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Failed to load sqlite-vec in connection: {e}")
        
        return conn

    def _ensure_db(self) -> None:
        """初始化数据库表结构"""
        try:
            with self._connect() as conn:
                # 1. 创建 knowledge_base 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        embedding_model_id TEXT NOT NULL,
                        status TEXT DEFAULT 'READY',
                        chunk_size INTEGER DEFAULT 500,
                        chunk_overlap INTEGER DEFAULT 50,
                        chunk_size_overrides_json TEXT DEFAULT '{}',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        user_id TEXT DEFAULT 'default',
                        tenant_id TEXT DEFAULT 'default'
                    );
                """)
                
                # 添加 status 字段（如果表已存在但字段不存在）
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN status TEXT DEFAULT 'READY'")
                except sqlite3.OperationalError:
                    pass
                # 添加 user_id 字段（兼容旧表）
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN user_id TEXT DEFAULT 'default'")
                    conn.execute("UPDATE knowledge_base SET user_id = 'default' WHERE user_id IS NULL")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN chunk_size INTEGER DEFAULT 500")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN chunk_overlap INTEGER DEFAULT 50")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE knowledge_base ADD COLUMN chunk_size_overrides_json TEXT DEFAULT '{}'")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute(
                        "ALTER TABLE knowledge_base ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                    )
                    conn.execute(
                        "UPDATE knowledge_base SET tenant_id = 'default' WHERE tenant_id IS NULL OR trim(tenant_id) = ''"
                    )
                except sqlite3.OperationalError:
                    pass

                # 2. 创建 document 表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS document (
                        id TEXT PRIMARY KEY,
                        knowledge_base_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        doc_type TEXT,
                        status TEXT DEFAULT 'UPLOADED',
                        chunks_count INTEGER DEFAULT 0,
                        file_path TEXT,
                        error_message TEXT,
                        content_hash TEXT,
                        current_version_id TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        user_id TEXT DEFAULT 'default',
                        tenant_id TEXT DEFAULT 'default',
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                    );
                """)
                
                # 添加 user_id 字段（兼容旧 document 表）
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN user_id TEXT DEFAULT 'default'")
                    conn.execute("UPDATE document SET user_id = 'default' WHERE user_id IS NULL")
                except sqlite3.OperationalError:
                    pass
                # 添加 status 字段（如果表已存在但字段不存在）
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN status TEXT DEFAULT 'UPLOADED'")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN chunks_count INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN file_path TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN error_message TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN content_hash TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN current_version_id TEXT")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE document ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute(
                        "ALTER TABLE document ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                    )
                    conn.execute(
                        "UPDATE document SET tenant_id = 'default' WHERE tenant_id IS NULL OR trim(tenant_id) = ''"
                    )
                except sqlite3.OperationalError:
                    pass
                # 若统一表已存在，尽量补齐 version_id 字段用于按版本检索隔离
                try:
                    conn.execute(f"ALTER TABLE {UNIFIED_CHUNKS_TABLE} ADD COLUMN version_id TEXT")
                except sqlite3.OperationalError:
                    pass

                # 3. 创建索引
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_document_kb_id 
                    ON document(knowledge_base_id);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_knowledge_base_user_tenant
                    ON knowledge_base(user_id, tenant_id);
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_document_kb_user_tenant
                    ON document(knowledge_base_id, user_id, tenant_id);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base_version (
                        id TEXT PRIMARY KEY,
                        knowledge_base_id TEXT NOT NULL,
                        version_label TEXT NOT NULL,
                        status TEXT DEFAULT 'ACTIVE',
                        notes TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_version_kb_id
                    ON knowledge_base_version(knowledge_base_id, created_at DESC);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS document_version (
                        id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        knowledge_base_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        content_hash TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (document_id) REFERENCES document(id),
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id),
                        FOREIGN KEY (version_id) REFERENCES knowledge_base_version(id)
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_doc_version_doc
                    ON document_version(document_id, created_at DESC);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kb_graph_entity (
                        id TEXT PRIMARY KEY,
                        knowledge_base_id TEXT NOT NULL,
                        version_id TEXT,
                        name TEXT NOT NULL,
                        entity_type TEXT DEFAULT 'generic',
                        source_doc_id TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_graph_entity_kb
                    ON kb_graph_entity(knowledge_base_id, version_id, name);
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kb_graph_relation (
                        id TEXT PRIMARY KEY,
                        knowledge_base_id TEXT NOT NULL,
                        version_id TEXT,
                        source_entity TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        target_entity TEXT NOT NULL,
                        confidence REAL DEFAULT 0.5,
                        source_doc_id TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(id)
                    );
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_kb_graph_rel_kb
                    ON kb_graph_relation(knowledge_base_id, version_id, source_entity, relation);
                """)

                # 4. 尝试启用 sqlite-vec（不再创建全局表，改为按知识库创建独立表）
                if self._try_enable_vec(conn):
                    self._vec_available = True
                    logger.info("[KnowledgeBaseStore] sqlite-vec enabled (per-KB tables)")
                else:
                    logger.warning("[KnowledgeBaseStore] sqlite-vec not available, embedding features disabled")

        except Exception as e:
            logger.error(f"[KnowledgeBaseStore] init db failed: {e}", exc_info=True)
            raise

    def _try_enable_vec(self, conn: sqlite3.Connection) -> bool:
        """尝试加载 sqlite-vec 扩展（不再创建全局表）"""
        try:
            conn.enable_load_extension(True)
            try:
                import sqlite_vec  # type: ignore
                sqlite_vec.load(conn)  # type: ignore
            finally:
                conn.enable_load_extension(False)
            return True
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] sqlite-vec extension not available: {e}")
            return False
    
    def _get_chunk_table_name(self, kb_id: str) -> str:
        """
        获取知识库对应的向量表名（旧版 per-KB 表）
        表名格式：embedding_chunk_{suffix}；suffix 与常规 kb_id 的旧规则一致，异常字符时用哈希。
        """
        return f"embedding_chunk_{_chunk_table_suffix_for_kb_id(kb_id)}"

    def _use_unified_chunks_table(self) -> bool:
        """是否使用统一单表 embedding_chunks（通过 sqlite_master 检查表是否存在，不依赖表内数据）"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (UNIFIED_CHUNKS_TABLE,),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _ensure_unified_vec_table(self, embedding_dim: int) -> None:
        """确保统一向量表 kb_chunks_vec 存在（由 VectorSearchProvider 创建）"""
        try:
            provider = get_vector_provider()
            if not provider.is_available():
                raise RuntimeError("Vector search provider is not available")
            if not provider.table_exists(UNIFIED_VEC_TABLE):
                provider.create_table(UNIFIED_VEC_TABLE, dimension=embedding_dim)
                logger.info(f"[KnowledgeBaseStore] Created unified vec table {UNIFIED_VEC_TABLE} dim={embedding_dim}")
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to ensure unified vec table: {e}")
            raise

    def _restore_unified_vectors_from_snapshot_if_needed(self, kb_id: str) -> None:
        """
        若统一向量表不存在，尝试从 Redis 快照恢复该 KB 的向量条目。
        """
        try:
            provider = get_vector_provider()
            if provider.table_exists(UNIFIED_VEC_TABLE):
                return
            embedding_dim = int(self.config.embedding_dim or 512)
            provider.create_table(UNIFIED_VEC_TABLE, dimension=embedding_dim)
            cached = self._snapshot_store.load_embeddings(kb_id)
            if not cached:
                return
            for rowid, embedding in cached.items():
                try:
                    provider.upsert_vector(
                        table_name=UNIFIED_VEC_TABLE,
                        vector_id=rowid,
                        embedding=embedding,
                    )
                except Exception:
                    continue
            logger.info(
                f"[KnowledgeBaseStore] Restored {len(cached)} vectors from Redis snapshot for KB {kb_id}"
            )
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Redis snapshot restore skipped for KB {kb_id}: {e}")

    def _ensure_kb_vec_table(self, kb_id: str, embedding_dim: int) -> None:
        """
        确保知识库的向量表存在且维度正确
        
        Args:
            kb_id: 知识库 ID
            embedding_dim: Embedding 维度
        """
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot create vec table")
        
        table_name = self._get_chunk_table_name(kb_id)
        
        with self._connect() as conn:
            if not self._try_enable_vec(conn):
                raise RuntimeError("sqlite-vec is not available")
            
            # 检查表是否存在
            try:
                # 尝试查询表，如果不存在会抛出异常
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                # 表已存在，检查维度（通过尝试插入一个测试向量来验证）
                # 注意：sqlite-vec 不支持直接查询表结构，我们通过异常来判断
                logger.debug(f"[KnowledgeBaseStore] Table {table_name} already exists")
            except sqlite3.OperationalError:
                # 表不存在，创建新表
                logger.info(f"[KnowledgeBaseStore] Creating vec table {table_name} with dim={embedding_dim}")
                conn.execute(f"""
                    CREATE VIRTUAL TABLE {table_name}
                    USING vec0(
                        embedding FLOAT[{embedding_dim}],
                        document_id TEXT,
                        chunk_id TEXT,
                        content TEXT
                    );
                """)
                conn.commit()
                logger.info(f"[KnowledgeBaseStore] Created vec table {table_name}")
    
    def _ensure_vec_table_dimension(self, kb_id: str, required_dim: int) -> None:
        """
        确保知识库的向量表存在且维度正确
        
        注意：sqlite-vec 不支持 ALTER TABLE，如果维度不匹配，需要删除重建
        由于每个知识库有独立的表，重建不会影响其他知识库
        
        Args:
            kb_id: 知识库 ID
            required_dim: 所需的维度
        """
        # 直接调用 _ensure_kb_vec_table，它会检查表是否存在并创建
        self._ensure_kb_vec_table(kb_id, required_dim)
    

    # =========================
    # Knowledge Base CRUD
    # =========================

    def read_knowledge_base_row(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """按 id 读取知识库行（不做 user/tenant ACL）。供索引、磁盘估算等已在上层完成授权校验的路径使用。"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM knowledge_base WHERE id = ?", (kb_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def create_knowledge_base(
        self,
        name: str,
        description: Optional[str],
        embedding_model_id: str,
        kb_id: Optional[str] = None,
        user_id: str = "default",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        chunk_size_overrides_json: Optional[str] = None,
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> str:
        """
        创建知识库
        
        Args:
            name: 知识库名称
            description: 描述
            embedding_model_id: embedding 模型 ID（如 "embedding:bge-small-zh"）
            kb_id: 可选，不提供则自动生成 UUID
            user_id: 用户 ID（多用户架构）
            
        Returns:
            知识库 ID
        """
        if kb_id is None:
            kb_id = f"kb_{uuid.uuid4().hex[:12]}"

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO knowledge_base (id, name, description, embedding_model_id, status, user_id, tenant_id, chunk_size, chunk_overlap, chunk_size_overrides_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                kb_id,
                name,
                description,
                embedding_model_id,
                KnowledgeBaseStatus.EMPTY,
                user_id,
                tenant_id,
                int(chunk_size),
                int(chunk_overlap),
                chunk_size_overrides_json or getattr(settings, "kb_chunk_size_overrides_json", "{}"),
            ))
            conn.commit()

        logger.info(f"[KnowledgeBaseStore] Created knowledge base: {kb_id} for user: {user_id} tenant: {tenant_id}")
        return kb_id

    def get_knowledge_base(
        self,
        kb_id: str,
        user_id: str = "default",
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> Optional[Dict[str, Any]]:
        """获取知识库信息（按用户与租户过滤）"""
        with self._connect() as conn:
            kb_exists = conn.execute(
                "SELECT user_id, tenant_id FROM knowledge_base WHERE id = ?",
                (kb_id,),
            ).fetchone()

            if not kb_exists:
                raise ResourceNotFoundError("KnowledgeBase", kb_id)

            raw_tid = kb_exists["tenant_id"] if "tenant_id" in kb_exists.keys() else None
            eff_tid = (str(raw_tid).strip() if raw_tid else "") or DEFAULT_KB_TENANT_ID

            if kb_exists["user_id"] != user_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)
            if eff_tid != tenant_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)

            row = conn.execute(
                """
                SELECT * FROM knowledge_base WHERE id = ? AND user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                """,
                (kb_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            ).fetchone()

            if row:
                kb_info = dict(row)
                if not kb_info.get("status"):
                    self._update_kb_status_from_documents(kb_id)
                    row = conn.execute(
                        """
                        SELECT * FROM knowledge_base WHERE id = ? AND user_id = ?
                        AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                        """,
                        (kb_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
                    ).fetchone()
                    if row:
                        kb_info = dict(row)
                return kb_info
        return None

    def list_knowledge_bases(
        self, user_id: str = "default", tenant_id: str = DEFAULT_KB_TENANT_ID
    ) -> List[Dict[str, Any]]:
        """列出用户的所有知识库（按租户过滤）"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_base WHERE user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                ORDER BY created_at DESC
                """,
                (user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_knowledge_base(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        chunk_size_overrides_json: Optional[str] = None,
        user_id: str = "default",
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> bool:
        """
        更新知识库信息
        
        Args:
            kb_id: 知识库 ID
            name: 新的名称（可选）
            description: 新的描述（可选）
            
        Returns:
            bool: 是否更新成功
        """
        if not self.get_knowledge_base(kb_id, user_id=user_id, tenant_id=tenant_id):
            return False
        
        updates = []
        params = []
        
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if chunk_size is not None:
            updates.append("chunk_size = ?")
            params.append(int(chunk_size))
        if chunk_overlap is not None:
            updates.append("chunk_overlap = ?")
            params.append(int(chunk_overlap))
        if chunk_size_overrides_json is not None:
            updates.append("chunk_size_overrides_json = ?")
            params.append(chunk_size_overrides_json)
        
        if not updates:
            return True  # 没有需要更新的字段
        
        params.append(kb_id)
        
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE knowledge_base SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
            
            logger.info(f"[KnowledgeBaseStore] Updated knowledge base: {kb_id}")
            return cursor.rowcount > 0

    def delete_knowledge_base(
        self,
        kb_id: str,
        user_id: str = "default",
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> bool:
        """删除知识库（级联删除相关文档、chunks 和向量表）。统一表下会清理 embedding_chunks 与 kb_chunks_vec。"""
        # 先检查 KB 是否存在
        with self._connect() as conn:
            kb_exists = conn.execute(
                "SELECT id, user_id, tenant_id FROM knowledge_base WHERE id = ?",
                (kb_id,),
            ).fetchone()

            if not kb_exists:
                raise ResourceNotFoundError("KnowledgeBase", kb_id)

            raw_tid = kb_exists["tenant_id"] if "tenant_id" in kb_exists.keys() else None
            eff_tid = (str(raw_tid).strip() if raw_tid else "") or DEFAULT_KB_TENANT_ID

            if kb_exists["user_id"] != user_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)
            if eff_tid != tenant_id:
                raise UserAccessDeniedError("KnowledgeBase", kb_id, user_id)
        
        # 后续删除操作...
        # 统一表：先删该 KB 在 embedding_chunks 中的行，并同步删除向量
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                        (kb_id,),
                    ).fetchall()
                    rowids = [r["id"] for r in rows]
                    if rowids:
                        conn.execute(
                            f"DELETE FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                            (kb_id,),
                        )
                        conn.commit()
                        provider = get_vector_provider()
                        if provider.is_available():
                            provider.delete_vectors(table_name=UNIFIED_VEC_TABLE, vector_ids=rowids)
                        logger.info(f"[KnowledgeBaseStore] Deleted {len(rowids)} chunks from {UNIFIED_CHUNKS_TABLE} for KB {kb_id}")
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Failed to delete unified chunks for KB {kb_id}: {e}")

        with self._connect() as conn:
            # 删除 per-KB 向量表（若存在）
            if self._vec_available:
                try:
                    table_name = self._get_chunk_table_name(kb_id)
                    conn.execute(f"DROP TABLE IF EXISTS {table_name};")
                    logger.info(f"[KnowledgeBaseStore] Dropped vec table {table_name} for KB {kb_id}")
                except Exception as e:
                    logger.warning(f"[KnowledgeBaseStore] Failed to drop vec table for KB {kb_id}: {e}")

            conn.execute(
                "DELETE FROM document WHERE knowledge_base_id = ?",
                (kb_id,),
            )
            cursor = conn.execute(
                """
                DELETE FROM knowledge_base WHERE id = ? AND user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                """,
                (kb_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                self._snapshot_store.clear_kb(kb_id)
            return cursor.rowcount > 0

    # =========================
    # Document CRUD
    # =========================

    def create_document(
        self,
        knowledge_base_id: str,
        source: str,
        doc_type: Optional[str] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
        status: str = "UPLOADED",
        user_id: str = "default",
        content_hash: Optional[str] = None,
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> str:
        """
        创建文档记录
        
        Args:
            knowledge_base_id: 所属知识库 ID
            source: 文档来源（文件名/URL）
            doc_type: 文档类型（pdf/docx/md 等）
            doc_id: 可选，不提供则自动生成 UUID
            file_path: 文件存储路径
            status: 文档状态
            user_id: 用户 ID（多用户架构）
            
        Returns:
            文档 ID
        """
        if doc_id is None:
            doc_id = f"doc_{uuid.uuid4().hex[:12]}"

        with self._connect() as conn:
            chk = conn.execute(
                """
                SELECT id FROM knowledge_base WHERE id = ? AND user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                """,
                (knowledge_base_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            ).fetchone()
            if not chk:
                raise ResourceNotFoundError("KnowledgeBase", knowledge_base_id)
            conn.execute("""
                INSERT INTO document (id, knowledge_base_id, source, doc_type, status, file_path, user_id, tenant_id, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                knowledge_base_id,
                source,
                doc_type,
                status,
                file_path,
                user_id,
                tenant_id,
                content_hash,
            ))
            conn.commit()

        logger.debug(f"[KnowledgeBaseStore] Created document: {doc_id} with status {status}")
        
        # 创建文档后更新知识库状态
        self._update_kb_status_from_documents(knowledge_base_id)
        
        return doc_id
    
    def update_document_status(
        self,
        doc_id: str,
        status: str,
        chunks_count: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新文档状态"""
        with self._connect() as conn:
            updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            
            if chunks_count is not None:
                updates.append("chunks_count = ?")
                params.append(chunks_count)
            
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)
            
            params.append(doc_id)
            
            conn.execute(
                f"UPDATE document SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
        
        logger.debug(f"[KnowledgeBaseStore] Updated document {doc_id} status to {status}")
        
        # 自动更新知识库状态
        doc = self.get_document(doc_id)
        if doc:
            kb_id = doc.get("knowledge_base_id")
            if kb_id:
                self._update_kb_status_from_documents(kb_id)

    def update_document_file_path(self, doc_id: str, file_path: Optional[str]) -> None:
        """持久化文档本地文件路径（上传保存文件后调用，供重索引等接口使用）"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE document
                SET file_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (file_path, doc_id),
            )
            conn.commit()

    def _compute_kb_status(self, kb_id: str) -> str:
        """
        根据所有文档的状态计算知识库状态
        
        规则：
        - 如果有任何文档处于索引中（UPLOADED, PARSING, PARSED, CHUNKING, CHUNKED, EMBEDDING）→ INDEXING
        - 如果有任何文档失败（FAILED_PARSE, FAILED_EMBED）→ ERROR
        - 如果所有文档都是 INDEXED → READY
        - 如果没有文档 → EMPTY
        """
        kb_row = self.read_knowledge_base_row(kb_id)
        if not kb_row:
            return KnowledgeBaseStatus.EMPTY
        uid = kb_row.get("user_id") or "default"
        tid = (str(kb_row.get("tenant_id") or "").strip()) or DEFAULT_KB_TENANT_ID
        docs = self.list_documents(kb_id, user_id=uid, tenant_id=tid)
        
        if not docs:
            return KnowledgeBaseStatus.EMPTY
        
        indexing_states = {
            DocumentStatus.UPLOADED,
            DocumentStatus.PARSING,
            DocumentStatus.PARSED,
            DocumentStatus.CHUNKING,
            DocumentStatus.CHUNKED,
            DocumentStatus.EMBEDDING,
        }
        
        failed_states = {
            DocumentStatus.FAILED_PARSE,
            DocumentStatus.FAILED_EMBED,
        }
        
        has_indexing = False
        has_failed = False
        all_indexed = True
        
        for doc in docs:
            status = doc.get("status", DocumentStatus.UPLOADED)
            if status in indexing_states:
                has_indexing = True
                all_indexed = False
            elif status in failed_states:
                has_failed = True
                all_indexed = False
            elif status != DocumentStatus.INDEXED:
                all_indexed = False
        
        if has_indexing:
            return KnowledgeBaseStatus.INDEXING
        elif has_failed:
            return KnowledgeBaseStatus.ERROR
        elif all_indexed:
            return KnowledgeBaseStatus.READY
        else:
            # 混合状态：有已索引的，也有失败的，但没有正在索引的
            return KnowledgeBaseStatus.ERROR

    def _update_kb_status_from_documents(self, kb_id: str) -> None:
        """根据文档状态更新知识库状态"""
        new_status = self._compute_kb_status(kb_id)
        self.update_knowledge_base_status(kb_id, new_status)

    def update_knowledge_base_status(self, kb_id: str, status: str) -> None:
        """更新知识库状态"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_base SET status = ? WHERE id = ?",
                (status, kb_id)
            )
            conn.commit()
        logger.debug(f"[KnowledgeBaseStore] Updated knowledge base {kb_id} status to {status}")

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """获取文档信息"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document WHERE id = ?",
                (doc_id,)
            ).fetchone()
            
            if row:
                return dict(row)
        return None

    def list_documents(
        self,
        knowledge_base_id: str,
        user_id: str = "default",
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> List[Dict[str, Any]]:
        """列出知识库下的所有文档（按用户与租户过滤）"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM document WHERE knowledge_base_id = ? AND user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                ORDER BY created_at DESC
                """,
                (knowledge_base_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_document(
        self,
        doc_id: str,
        user_id: str = "default",
        tenant_id: str = DEFAULT_KB_TENANT_ID,
    ) -> bool:
        """删除文档（不再级联删除 chunks，需要单独调用 delete_document_chunks）"""
        # 先获取文档信息，以便后续更新知识库状态
        doc = self.get_document(doc_id)
        if not doc:
            return False
        kb_id = doc.get("knowledge_base_id")

        # 验证用户与租户权限
        if doc.get("user_id") != user_id:
            logger.warning(f"[KnowledgeBaseStore] Document {doc_id} does not belong to user {user_id}")
            return False
        doc_tid = (str(doc.get("tenant_id") or "").strip()) or DEFAULT_KB_TENANT_ID
        if doc_tid != tenant_id:
            logger.warning(
                f"[KnowledgeBaseStore] Document {doc_id} tenant mismatch (expected {tenant_id}, got {doc_tid})"
            )
            return False
        
        with self._connect() as conn:
            # 删除 document
            cursor = conn.execute(
                """
                DELETE FROM document WHERE id = ? AND user_id = ?
                AND coalesce(nullif(trim(tenant_id), ''), ?) = ?
                """,
                (doc_id, user_id, DEFAULT_KB_TENANT_ID, tenant_id),
            )
            conn.commit()
            
            result = cursor.rowcount > 0
        
        # 删除文档后更新知识库状态
        if result and kb_id:
            self._update_kb_status_from_documents(kb_id)
        
        return result
    
    def delete_document_chunks(self, kb_id: str, doc_id: str) -> int:
        """删除文档的所有 chunks。优先使用统一表。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"SELECT id FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ? AND document_id = ?",
                        (kb_id, doc_id),
                    ).fetchall()
                    rowids = [r["id"] for r in rows]
                    if not rowids:
                        return 0
                    conn.execute(
                        f"DELETE FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ? AND document_id = ?",
                        (kb_id, doc_id),
                    )
                    conn.commit()
                provider = get_vector_provider()
                if provider.is_available():
                    provider.delete_vectors(table_name=UNIFIED_VEC_TABLE, vector_ids=rowids)
                self._snapshot_store.delete_embeddings(kb_id, [int(x) for x in rowids])
                logger.info(f"[KnowledgeBaseStore] Deleted {len(rowids)} chunks for document {doc_id} from {UNIFIED_CHUNKS_TABLE}")
                return len(rowids)
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified delete_document_chunks failed: {e}")

        if not self._vec_available:
            return 0
        table_name = self._get_chunk_table_name(kb_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            return 0
        with self._connect() as conn:
            count_row = conn.execute(
                f"SELECT count(*) as cnt FROM {table_name} WHERE document_id = ?", (doc_id,)
            ).fetchone()
            chunk_count = count_row["cnt"] if count_row else 0
            conn.execute(f"DELETE FROM {table_name} WHERE document_id = ?", (doc_id,))
            conn.commit()
        logger.info(f"[KnowledgeBaseStore] Deleted {chunk_count} chunks for document {doc_id} from {table_name}")
        return chunk_count

    # =========================
    # Embedding Chunk Operations
    # =========================

    def _unified_table_has_metadata_json(self) -> bool:
        """检测统一表是否包含 metadata_json 列（Alembic 迁移 d4e5f6a7b8c9 之后有）"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM pragma_table_info(?) WHERE name = ?",
                    (UNIFIED_CHUNKS_TABLE, "metadata_json"),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _unified_table_has_version_id(self) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM pragma_table_info(?) WHERE name = ?",
                    (UNIFIED_CHUNKS_TABLE, "version_id"),
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def insert_chunk(
        self,
        knowledge_base_id: str,
        document_id: str,
        chunk_id: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        version_id: Optional[str] = None,
    ) -> None:
        """
        插入 embedding chunk（优先使用统一表 embedding_chunks + kb_chunks_vec）。
        metadata 为可选扩展字段，写入 metadata_json（需先执行 Alembic 迁移 d4e5f6a7b8c9）。
        """
        actual_dim = len(embedding)

        if self._use_unified_chunks_table():
            try:
                self._ensure_unified_vec_table(actual_dim)
                provider = get_vector_provider()
                if not provider.is_available():
                    raise RuntimeError("Vector search provider is not available")
                with self._connect() as conn:
                    has_meta = self._unified_table_has_metadata_json()
                    has_version_id = self._unified_table_has_version_id()
                    if has_meta and metadata is not None and has_version_id:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content, metadata_json, version_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content, json.dumps(metadata), version_id),
                        )
                    elif has_meta and metadata is not None:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content, metadata_json)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content, json.dumps(metadata)),
                        )
                    elif has_version_id:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content, version_id)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content, version_id),
                        )
                    else:
                        conn.execute(
                            f"""
                            INSERT INTO {UNIFIED_CHUNKS_TABLE}
                            (knowledge_base_id, document_id, chunk_id, content)
                            VALUES (?, ?, ?, ?)
                            """,
                            (knowledge_base_id, document_id, chunk_id, content),
                        )
                    rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.commit()
                provider.upsert_vector(
                    table_name=UNIFIED_VEC_TABLE,
                    vector_id=rowid,
                    embedding=embedding,
                )
                self._snapshot_store.save_embedding(knowledge_base_id, int(rowid), embedding)
                logger.debug(f"[KnowledgeBaseStore] Inserted chunk {chunk_id} into {UNIFIED_CHUNKS_TABLE}")
                return
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified insert failed, falling back to per-KB table: {e}")

        # 旧版：per-KB 向量表
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot insert chunks")
        self._ensure_kb_vec_table(knowledge_base_id, actual_dim)
        table_name = self._get_chunk_table_name(knowledge_base_id)
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {table_name}
                (embedding, document_id, chunk_id, content)
                VALUES (?, ?, ?, ?)
                """,
                (json.dumps(embedding), document_id, chunk_id, content),
            )
            conn.commit()
        logger.debug(f"[KnowledgeBaseStore] Inserted chunk: {chunk_id} into {table_name}")

    def search_chunks(
        self,
        knowledge_base_id: str,
        query_embedding: List[float],
        limit: int = 5,
        max_distance: Optional[float] = None,
        version_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        向量检索（Top-K）。优先使用统一表 + VectorSearchProvider。
        """
        if self._use_unified_chunks_table():
            try:
                self._restore_unified_vectors_from_snapshot_if_needed(knowledge_base_id)
                provider = get_vector_provider()
                if provider.is_available():
                    results = provider.search(
                        table_name=UNIFIED_VEC_TABLE,
                        query_vector=query_embedding,
                        limit=limit,
                        filters={
                            **({"knowledge_base_id": knowledge_base_id}),
                            **({"version_id": version_id} if version_id and self._unified_table_has_version_id() else {}),
                        },
                        business_table=UNIFIED_CHUNKS_TABLE,
                    )
                    if not results:
                        return []
                    rowids = [int(r) for _, r in results]
                    placeholders = ",".join(["?"] * len(rowids))
                    has_meta = self._unified_table_has_metadata_json()
                    has_ver_col = self._unified_table_has_version_id()
                    meta_col = ", c.metadata_json" if has_meta else ""
                    ver_col = ", c.version_id" if has_ver_col else ""
                    ver_where = " AND c.version_id = ?" if version_id and has_ver_col else ""
                    with self._connect() as conn:
                        rows = conn.execute(
                            f"""
                            SELECT c.id, c.content, c.document_id, c.chunk_id, c.knowledge_base_id{meta_col}{ver_col},
                                   d.source as doc_source, d.doc_type
                            FROM {UNIFIED_CHUNKS_TABLE} c
                            LEFT JOIN document d ON d.id = c.document_id
                            WHERE c.id IN ({placeholders}) AND c.knowledge_base_id = ? {ver_where}
                            """,
                            tuple(rowids) + ((knowledge_base_id, version_id) if version_id and has_ver_col else (knowledge_base_id,)),
                        ).fetchall()
                    rowid_to_row = {r["id"]: r for r in rows}
                    out = []
                    for distance, rowid in results:
                        r = rowid_to_row.get(int(rowid))
                        if r:
                            item = {
                                "content": r["content"],
                                "distance": float(distance),
                                "document_id": r["document_id"],
                                "chunk_id": r["chunk_id"],
                                "version_id": (r["version_id"] if has_ver_col else None),
                                "doc_source": r["doc_source"],
                                "doc_type": r["doc_type"],
                            }
                            if has_meta and r.get("metadata_json"):
                                try:
                                    item["metadata"] = json.loads(r["metadata_json"])
                                except (TypeError, ValueError):
                                    pass
                            if max_distance is None or item["distance"] <= max_distance:
                                out.append(item)
                    return out
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified search failed, falling back: {e}")

        # 旧版：per-KB 表
        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot search chunks")
        table_name = self._get_chunk_table_name(knowledge_base_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            migrated = self.migrate_chunks_from_old_table(knowledge_base_id)
            if migrated == 0:
                return []
        with self._connect() as conn:
            query_sql = f"""
                SELECT c.content, c.distance, c.document_id, c.chunk_id,
                       d.source as doc_source, d.doc_type
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ? AND c.embedding MATCH ? AND c.k = ?
                ORDER BY c.distance
            """
            rows = conn.execute(
                query_sql,
                (knowledge_base_id, json.dumps(query_embedding), limit),
            ).fetchall()
        results = [
            {
                "content": row["content"],
                "distance": row["distance"],
                "document_id": row["document_id"],
                "chunk_id": row["chunk_id"],
                "doc_source": row["doc_source"],
                "doc_type": row["doc_type"],
            }
            for row in rows
        ]
        if max_distance is not None:
            results = [r for r in results if r["distance"] <= max_distance]
        return results

    def search_chunks_multi_kb(
        self,
        knowledge_base_ids: List[str],
        query_embedding: List[float],
        limit: int = 5,
        max_distance: Optional[float] = None,
        version_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """多知识库向量检索。统一表下按 kb 分别检索后合并排序取 top limit。"""
        if not knowledge_base_ids:
            return []

        if self._use_unified_chunks_table():
            try:
                combined: List[Dict[str, Any]] = []
                per_kb = max(1, (limit + len(knowledge_base_ids) - 1) // len(knowledge_base_ids))
                for kb_id in knowledge_base_ids:
                    part = self.search_chunks(
                        knowledge_base_id=kb_id,
                        query_embedding=query_embedding,
                        limit=per_kb,
                        max_distance=max_distance,
                        version_id=version_id,
                    )
                    for r in part:
                        r["knowledge_base_id"] = kb_id
                        combined.append(r)
                combined.sort(key=lambda x: x["distance"])
                return combined[:limit]
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified search_chunks_multi_kb failed: {e}")

        if not self._vec_available:
            raise RuntimeError("sqlite-vec is not available, cannot search chunks")

        # 过滤出存在的表，如果不存在则尝试迁移
        valid_kb_ids = []
        table_names = []
        with self._connect() as conn:
            for kb_id in knowledge_base_ids:
                table_name = self._get_chunk_table_name(kb_id)
                try:
                    # 检查表是否存在
                    conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                    valid_kb_ids.append(kb_id)
                    table_names.append(table_name)
                except sqlite3.OperationalError:
                    # 表不存在，尝试从旧表迁移数据
                    logger.info(f"[KnowledgeBaseStore] Vec table {table_name} does not exist for KB {kb_id}, attempting migration...")
                    migrated = self.migrate_chunks_from_old_table(kb_id)
                    if migrated > 0:
                        # 迁移成功，重新检查表
                        try:
                            conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
                            valid_kb_ids.append(kb_id)
                            table_names.append(table_name)
                            logger.info(f"[KnowledgeBaseStore] Migration successful, {table_name} is now available")
                        except sqlite3.OperationalError:
                            logger.debug(f"[KnowledgeBaseStore] Vec table {table_name} still does not exist after migration for KB {kb_id}")
                    else:
                        logger.debug(f"[KnowledgeBaseStore] Vec table {table_name} does not exist for KB {kb_id}, skipping")
                    continue
        
        if not valid_kb_ids:
            logger.warning(f"[KnowledgeBaseStore] No valid vec tables found for KBs: {knowledge_base_ids}")
            return []

        # 构建 UNION 查询
        # 注意：每个表的结构相同，但我们需要在 SELECT 中添加 knowledge_base_id
        union_parts = []
        query_params = []
        
        # sqlite-vec 要求每个 MATCH 查询必须有 LIMIT 或 k = ? 约束
        # 为了确保每个子查询都能返回足够的结果，我们给每个子查询设置一个较大的 LIMIT
        # 然后在外部再限制最终结果数量
        per_table_limit = limit * len(valid_kb_ids)  # 每个表返回更多结果，确保最终有足够的选择
        
        for kb_id, table_name in zip(valid_kb_ids, table_names):
            # sqlite-vec 要求 MATCH 查询必须有 k = ? 约束（在 WHERE 子句中）
            # 或者使用 LIMIT（但必须在 ORDER BY 之后）
            # 我们使用 k = ? 方式，因为它更符合 sqlite-vec 的语义
            union_parts.append(f"""
                SELECT 
                    c.content, 
                    c.distance, 
                    c.document_id, 
                    c.chunk_id,
                    ? as knowledge_base_id,
                    d.source as doc_source,
                    d.doc_type
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ?
                AND c.embedding MATCH ?
                AND c.k = ?
            """)
            query_params.extend([kb_id, kb_id, json.dumps(query_embedding), per_table_limit])
        
        # 组合 UNION 查询
        union_query = " UNION ALL ".join(union_parts)
        final_query = f"""
            SELECT * FROM (
                {union_query}
            ) ORDER BY distance LIMIT ?
        """
        query_params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(final_query, query_params).fetchall()

            results = [
                {
                    "content": row["content"],
                    "distance": row["distance"],
                    "document_id": row["document_id"],
                    "chunk_id": row["chunk_id"],
                    "knowledge_base_id": row["knowledge_base_id"],
                    "doc_source": row["doc_source"],
                    "doc_type": row["doc_type"]
                } 
                for row in rows
            ]
            
            # 应用距离过滤
            if max_distance is not None:
                results = [r for r in results if r["distance"] <= max_distance]
            
            return results

    def search_chunks_keyword_multi_kb(
        self,
        knowledge_base_ids: List[str],
        query_text: str,
        limit: int = 10,
        version_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        关键词检索（轻量 BM25-like）。优先走统一表，按 token 命中数与覆盖率排序。
        该实现不依赖 sqlite FTS，避免环境差异导致不可用。
        """
        if not knowledge_base_ids:
            return []
        tokens = self._tokenize_query(query_text)
        if not tokens:
            return []

        if self._use_unified_chunks_table():
            placeholders_kb = ",".join(["?"] * len(knowledge_base_ids))
            like_clauses = " OR ".join(["LOWER(c.content) LIKE ?" for _ in tokens])
            has_ver_col = self._unified_table_has_version_id()
            ver_where = " AND c.version_id = ?" if version_id and has_ver_col else ""
            sql = f"""
                SELECT
                    c.id,
                    c.content,
                    c.document_id,
                    c.chunk_id,
                    c.knowledge_base_id,
                    d.source as doc_source,
                    d.doc_type
                FROM {UNIFIED_CHUNKS_TABLE} c
                LEFT JOIN document d ON d.id = c.document_id
                WHERE c.knowledge_base_id IN ({placeholders_kb})
                  AND ({like_clauses})
                  {ver_where}
                LIMIT ?
            """
            params: List[Any] = list(knowledge_base_ids) + [f"%{t}%" for t in tokens]
            if version_id and has_ver_col:
                params.append(version_id)
            params.append(max(limit * 8, 50))
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            scored = []
            for row in rows:
                text = row["content"] or ""
                score = self._keyword_score(tokens, text)
                if score <= 0:
                    continue
                scored.append(
                    {
                        "content": text,
                        "distance": max(0.0, 1.0 - score),
                        "keyword_score": score,
                        "document_id": row["document_id"],
                        "chunk_id": row["chunk_id"],
                        "knowledge_base_id": row["knowledge_base_id"],
                        "version_id": version_id,
                        "doc_source": row["doc_source"],
                        "doc_type": row["doc_type"],
                    }
                )
            scored.sort(key=lambda x: x["keyword_score"], reverse=True)
            return scored[:limit]
        return []

    def hybrid_search_chunks_multi_kb(
        self,
        knowledge_base_ids: List[str],
        query_text: str,
        query_embedding: List[float],
        keyword_limit: int = 20,
        vector_limit: int = 20,
        rerank_limit: int = 10,
        min_relevance_score: float = 0.5,
        max_distance: Optional[float] = None,
        version_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        多阶段检索：
        1) keyword stage 取精确匹配候选
        2) vector stage 取语义候选
        3) 融合重排并阈值过滤
        """
        keyword_results = self.search_chunks_keyword_multi_kb(
            knowledge_base_ids=knowledge_base_ids,
            query_text=query_text,
            limit=keyword_limit,
            version_id=version_id,
        )
        vector_results: List[Dict[str, Any]] = []
        if self._vec_available:
            vector_results = self.search_chunks_multi_kb(
                knowledge_base_ids=knowledge_base_ids,
                query_embedding=query_embedding,
                limit=vector_limit,
                max_distance=max_distance,
                version_id=version_id,
            )

        merged: Dict[str, Dict[str, Any]] = {}
        for item in keyword_results:
            key = self._chunk_dedup_key(item)
            merged[key] = dict(item)
        for item in vector_results:
            key = self._chunk_dedup_key(item)
            if key not in merged:
                merged[key] = dict(item)
            else:
                # 保留更小 distance，同时叠加 keyword_score
                old = merged[key]
                old["distance"] = min(float(old.get("distance", 1.0)), float(item.get("distance", 1.0)))
                if "keyword_score" in item and "keyword_score" not in old:
                    old["keyword_score"] = item["keyword_score"]
                merged[key] = old

        tokens = self._tokenize_query(query_text)
        reranked: List[Dict[str, Any]] = []
        for item in merged.values():
            text = item.get("content", "") or ""
            lexical = float(item.get("keyword_score", self._keyword_score(tokens, text)))
            vec_rel = max(0.0, 1.0 - float(item.get("distance", 1.0)))
            # 轻量重排：模拟 cross-encoder 的“词面 + 语义”综合相关性
            relevance = min(1.0, 0.55 * lexical + 0.45 * vec_rel)
            item["keyword_score"] = lexical
            item["vector_relevance"] = vec_rel
            item["relevance_score"] = relevance
            if relevance >= min_relevance_score:
                reranked.append(item)

        reranked.sort(key=lambda x: x.get("relevance_score", 0.0), reverse=True)
        return reranked[:rerank_limit]

    def _tokenize_query(self, query_text: str) -> List[str]:
        text = (query_text or "").strip().lower()
        if not text:
            return []
        # 中英混合：英文按词切分，中文按 2-gram 粗分
        en_tokens = re.findall(r"[a-z0-9_]{2,}", text)
        zh_chars = re.findall(r"[\u4e00-\u9fff]", text)
        zh_tokens = ["".join(zh_chars[i:i + 2]) for i in range(max(0, len(zh_chars) - 1))]
        tokens = en_tokens + zh_tokens
        # 去重并限制长度，避免 SQL LIKE 子句过长
        seen = set()
        out: List[str] = []
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= 8:
                break
        return out

    def _keyword_score(self, tokens: List[str], content: str) -> float:
        if not tokens:
            return 0.0
        text = (content or "").lower()
        hits = 0
        freq = 0
        for token in tokens:
            c = text.count(token)
            if c > 0:
                hits += 1
                freq += c
        if hits == 0:
            return 0.0
        coverage = hits / max(len(tokens), 1)
        freq_score = min(1.0, freq / max(len(tokens) * 2, 1))
        return min(1.0, 0.7 * coverage + 0.3 * freq_score)

    def _chunk_dedup_key(self, item: Dict[str, Any]) -> str:
        return (
            f'{item.get("knowledge_base_id", "")}::'
            f'{item.get("document_id", "")}::'
            f'{item.get("chunk_id", "")}'
        )

    def get_chunk_count(self, knowledge_base_id: Optional[str] = None) -> int:
        """获取 chunk 数量。优先使用统一表。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    if knowledge_base_id:
                        row = conn.execute(
                            f"SELECT count(*) as cnt FROM {UNIFIED_CHUNKS_TABLE} WHERE knowledge_base_id = ?",
                            (knowledge_base_id,),
                        ).fetchone()
                    else:
                        row = conn.execute(f"SELECT count(*) as cnt FROM {UNIFIED_CHUNKS_TABLE}").fetchone()
                    return row["cnt"] if row else 0
            except Exception:
                pass
        if not self._vec_available:
            return 0
        with self._connect() as conn:
            if knowledge_base_id:
                table_name = self._get_chunk_table_name(knowledge_base_id)
                try:
                    row = conn.execute(f"SELECT count(*) as cnt FROM {table_name}").fetchone()
                    return row["cnt"] if row else 0
                except sqlite3.OperationalError:
                    return 0
            else:
                total = 0
                kb_rows = conn.execute("SELECT id FROM knowledge_base").fetchall()
                for kb_row in kb_rows:
                    kb_id = kb_row["id"]
                    table_name = self._get_chunk_table_name(kb_id)
                    try:
                        row = conn.execute(f"SELECT count(*) as cnt FROM {table_name}").fetchone()
                        if row:
                            total += row["cnt"]
                    except sqlite3.OperationalError:
                        continue
                return total

    def list_chunks(
        self,
        knowledge_base_id: str,
        document_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出 chunks。优先使用统一表 embedding_chunks。"""
        if self._use_unified_chunks_table():
            try:
                with self._connect() as conn:
                    has_meta = self._unified_table_has_metadata_json()
                    cols = "chunk_id, document_id, content" + (", metadata_json" if has_meta else "")
                    query = f"""
                        SELECT {cols}
                        FROM {UNIFIED_CHUNKS_TABLE}
                        WHERE knowledge_base_id = ?
                    """
                    params: List[Any] = [knowledge_base_id]
                    if document_id:
                        query += " AND document_id = ?"
                        params.append(document_id)
                    query += " ORDER BY chunk_id LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    rows = conn.execute(query, params).fetchall()
                out = []
                for i, r in enumerate(rows):
                    item = {"chunk_id": r["chunk_id"], "document_id": r["document_id"], "content": r["content"], "index": offset + i}
                    if has_meta and r.get("metadata_json"):
                        try:
                            item["metadata"] = json.loads(r["metadata_json"])
                        except (TypeError, ValueError):
                            pass
                    out.append(item)
                return out
            except Exception as e:
                logger.warning(f"[KnowledgeBaseStore] Unified list_chunks failed: {e}")

        if not self._vec_available:
            return []
        table_name = self._get_chunk_table_name(knowledge_base_id)
        try:
            with self._connect() as conn:
                conn.execute(f"SELECT count(*) FROM {table_name} LIMIT 1;").fetchone()
        except sqlite3.OperationalError:
            return []
        with self._connect() as conn:
            query = f"""
                SELECT c.chunk_id, c.document_id, c.content
                FROM {table_name} c
                LEFT JOIN document d ON c.document_id = d.id
                WHERE d.knowledge_base_id = ?
            """
            params = [knowledge_base_id]
            if document_id:
                query += " AND c.document_id = ?"
                params.append(document_id)
            query += " ORDER BY c.chunk_id LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
        return [
            {"chunk_id": r["chunk_id"], "document_id": r["document_id"], "content": r["content"], "index": offset + i}
            for i, r in enumerate(rows)
        ]
    
    def get_knowledge_base_disk_size(self, kb_id: str) -> Dict[str, Any]:
        """
        计算知识库的磁盘使用量
        
        包括：
        1. 原始文件大小（knowledge_bases/{kb_id}/raw/ 目录）
        2. 数据库中的向量数据大小（统一表 embedding_chunks/kb_chunks_vec 或 per-KB 表）
        3. 数据库中的元数据大小（document 表中的记录）
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            Dict with:
            - raw_files_size: 原始文件总大小（字节）
            - vector_table_size: 向量表大小（字节）
            - metadata_size: 元数据大小（字节）
            - total_size: 总大小（字节）
        """
        from core.knowledge.file_storage import FileStorage
        
        result = {
            "raw_files_size": 0,
            "vector_table_size": 0,
            "metadata_size": 0,
            "total_size": 0,
        }
        
        # 1. 计算原始文件大小
        try:
            storage_dir = FileStorage.get_kb_storage_path(kb_id)
            if storage_dir.exists():
                for file_path in storage_dir.iterdir():
                    if file_path.is_file():
                        result["raw_files_size"] += file_path.stat().st_size
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate raw files size for KB {kb_id}: {e}")
        
        # 2. 计算数据库中的向量表大小（统一表或 per-KB 表）
        try:
            chunk_count = self.get_chunk_count(kb_id)
            if chunk_count == 0:
                result["vector_table_size"] = 0
            else:
                actual_embedding_dim = self.config.embedding_dim
                if self._use_unified_chunks_table() or self._vec_available:
                    kb_info = self.read_knowledge_base_row(kb_id)
                    if kb_info:
                        try:
                            from core.models.registry import get_model_registry
                            model_registry = get_model_registry()
                            embedding_model = model_registry.get_model(kb_info.get("embedding_model_id", ""))
                            if embedding_model:
                                actual_embedding_dim = embedding_model.metadata.get("embedding_dim", self.config.embedding_dim)
                        except Exception:
                            pass
                embedding_size = actual_embedding_dim * 4
                metadata_per_chunk = 200
                chunk_size = embedding_size + metadata_per_chunk
                result["vector_table_size"] = int(chunk_count * chunk_size * 1.2)  # 20% overhead
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate vector table size for KB {kb_id}: {e}")
        
        # 3. 计算元数据大小（document 表中的记录）
        try:
            with self._connect() as conn:
                # 获取该知识库的所有文档记录
                docs = conn.execute(
                    "SELECT id, source, doc_type, file_path FROM document WHERE knowledge_base_id = ?",
                    (kb_id,)
                ).fetchall()
                
                # 计算每条记录的实际大小
                for doc in docs:
                    # ID: 约 32 bytes (UUID)
                    # knowledge_base_id: 约 32 bytes
                    # source: 文件名长度
                    # doc_type: 约 10 bytes
                    # status: 约 20 bytes
                    # chunks_count: 约 8 bytes
                    # file_path: 路径长度
                    # created_at, updated_at: 约 30 bytes each
                    # error_message: 通常为空
                    # 注意：sqlite3.Row 对象使用索引或列名访问，不是 dict
                    source = doc["source"] if "source" in doc.keys() else ""
                    doc_type = doc["doc_type"] if "doc_type" in doc.keys() else ""
                    file_path = doc["file_path"] if "file_path" in doc.keys() else ""
                    record_size = (
                        32 +  # id
                        32 +  # knowledge_base_id
                        len(source or "") +
                        len(doc_type or "") +
                        len(file_path or "") +
                        20 +  # status
                        8 +   # chunks_count
                        60    # timestamps
                    )
                    result["metadata_size"] += record_size
        except Exception as e:
            logger.warning(f"[KnowledgeBaseStore] Failed to calculate metadata size for KB {kb_id}: {e}")
        
        # 4. 计算总大小
        result["total_size"] = (
            result["raw_files_size"] +
            result["vector_table_size"] +
            result["metadata_size"]
        )
        
        return result
    
    def migrate_chunks_from_old_table(self, kb_id: str) -> int:
        """
        从旧的共享表 embedding_chunk 迁移数据到新的独立表
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            迁移的 chunk 数量
        """
        if not self._vec_available:
            logger.warning(f"[KnowledgeBaseStore] sqlite-vec not available, cannot migrate chunks for KB {kb_id}")
            return 0
        
        old_table = "embedding_chunk"
        new_table = self._get_chunk_table_name(kb_id)
        
        migrated_count = 0
        
        with self._connect() as conn:
            # 检查旧表是否存在
            try:
                old_count = conn.execute(
                    f"SELECT count(*) as cnt FROM {old_table} WHERE knowledge_base_id = ?",
                    (kb_id,)
                ).fetchone()
                if not old_count or old_count["cnt"] == 0:
                    logger.debug(f"[KnowledgeBaseStore] No chunks to migrate from old table for KB {kb_id}")
                    return 0
                
                logger.info(f"[KnowledgeBaseStore] Found {old_count['cnt']} chunks in old table for KB {kb_id}, starting migration...")
            except sqlite3.OperationalError:
                logger.debug(f"[KnowledgeBaseStore] Old table {old_table} does not exist, nothing to migrate")
                return 0
            
            # 检查新表是否存在，如果不存在则创建
            try:
                conn.execute(f"SELECT count(*) FROM {new_table} LIMIT 1;").fetchone()
                logger.debug(f"[KnowledgeBaseStore] New table {new_table} already exists")
            except sqlite3.OperationalError:
                # 新表不存在，需要创建
                # 获取第一个 chunk 的 embedding 维度来确定表结构
                sample = conn.execute(
                    f"SELECT embedding FROM {old_table} WHERE knowledge_base_id = ? LIMIT 1",
                    (kb_id,)
                ).fetchone()
                if sample:
                    # 解析 embedding JSON 获取维度
                    import json
                    embedding = json.loads(sample["embedding"])
                    dim = len(embedding)
                    logger.info(f"[KnowledgeBaseStore] Creating new table {new_table} with dim={dim}")
                    self._ensure_kb_vec_table(kb_id, dim)
            
            # 从旧表读取数据并插入到新表
            rows = conn.execute(
                f"""
                SELECT embedding, document_id, chunk_id, content
                FROM {old_table}
                WHERE knowledge_base_id = ?
                """,
                (kb_id,)
            ).fetchall()
            
            for row in rows:
                try:
                    conn.execute(f"""
                        INSERT INTO {new_table}
                        (embedding, document_id, chunk_id, content)
                        VALUES (?, ?, ?, ?)
                    """, (
                        row["embedding"],  # 已经是 JSON 格式
                        row["document_id"],
                        row["chunk_id"],
                        row["content"],
                    ))
                    migrated_count += 1
                except Exception as e:
                    logger.warning(f"[KnowledgeBaseStore] Failed to migrate chunk {row['chunk_id']}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"[KnowledgeBaseStore] Migrated {migrated_count} chunks from old table to {new_table}")
        
        return migrated_count

    # =========================
    # Utility Methods
    # =========================

    def health(self) -> Dict[str, Any]:
        """返回健康状态"""
        return {
            "status": "ok",
            "vec_available": self._vec_available,
            "embedding_dim": self.config.embedding_dim,
        }

    # =========================
    # Versioning & Incremental Indexing
    # =========================

    def create_kb_version(
        self,
        kb_id: str,
        version_label: str,
        notes: Optional[str] = None,
        status: str = "ACTIVE",
    ) -> str:
        version_id = f"kbv_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_base_version (id, knowledge_base_id, version_label, status, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (version_id, kb_id, version_label, status, notes),
            )
            conn.commit()
        return version_id

    def list_kb_versions(self, kb_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_base_version WHERE knowledge_base_id = ? ORDER BY created_at DESC",
                (kb_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_kb_version_id(
        self,
        kb_id: str,
        version_id: Optional[str] = None,
        version_label: Optional[str] = None,
    ) -> Optional[str]:
        """
        解析版本标识：
        - 优先使用显式 version_id
        - 其次按 version_label 查询
        - 均为空则返回最新版本
        """
        if version_id:
            return version_id
        with self._connect() as conn:
            if version_label:
                row = conn.execute(
                    """
                    SELECT id FROM knowledge_base_version
                    WHERE knowledge_base_id = ? AND version_label = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (kb_id, version_label),
                ).fetchone()
                if row:
                    return str(row["id"])
            latest = conn.execute(
                """
                SELECT id FROM knowledge_base_version
                WHERE knowledge_base_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (kb_id,),
            ).fetchone()
            return str(latest["id"]) if latest else None

    def get_latest_kb_version(self, kb_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM knowledge_base_version
                WHERE knowledge_base_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (kb_id,),
            ).fetchone()
            return dict(row) if row else None

    def ensure_default_kb_version(self, kb_id: str) -> str:
        latest = self.get_latest_kb_version(kb_id)
        if latest:
            return str(latest["id"])
        return self.create_kb_version(kb_id=kb_id, version_label="v1", notes="Initial version")

    def add_document_version(
        self,
        document_id: str,
        knowledge_base_id: str,
        version_id: str,
        content_hash: Optional[str] = None,
    ) -> str:
        record_id = f"docv_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_version (id, document_id, knowledge_base_id, version_id, content_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_id, document_id, knowledge_base_id, version_id, content_hash),
            )
            conn.execute(
                "UPDATE document SET current_version_id = ?, content_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (version_id, content_hash, document_id),
            )
            conn.commit()
        return record_id

    def get_latest_document_hash(self, doc_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content_hash FROM document_version
                WHERE document_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            if row and row["content_hash"]:
                return str(row["content_hash"])
        with self._connect() as conn:
            row = conn.execute("SELECT content_hash FROM document WHERE id = ?", (doc_id,)).fetchone()
            if row and row["content_hash"]:
                return str(row["content_hash"])
        return None

    def should_reindex_document(self, doc_id: str, new_content_hash: Optional[str]) -> bool:
        if not new_content_hash:
            return True
        latest_hash = self.get_latest_document_hash(doc_id)
        if not latest_hash:
            return True
        return latest_hash != new_content_hash

    def update_document_content_hash(self, doc_id: str, content_hash: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE document SET content_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (content_hash, doc_id),
            )
            conn.commit()

    # =========================
    # Knowledge Graph
    # =========================

    def upsert_graph_triples(
        self,
        kb_id: str,
        triples: List[Dict[str, Any]],
        source_doc_id: Optional[str] = None,
        version_id: Optional[str] = None,
    ) -> int:
        if not triples:
            return 0
        inserted = 0
        with self._connect() as conn:
            for t in triples:
                source_entity = (t.get("source") or "").strip()
                relation = (t.get("relation") or "").strip()
                target_entity = (t.get("target") or "").strip()
                if not source_entity or not relation or not target_entity:
                    continue
                confidence = float(t.get("confidence", 0.6))
                rel_id = f"rel_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO kb_graph_relation
                    (id, knowledge_base_id, version_id, source_entity, relation, target_entity, confidence, source_doc_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rel_id, kb_id, version_id, source_entity, relation, target_entity, confidence, source_doc_id),
                )
                inserted += 1
            conn.commit()
        return inserted

    def search_graph_relations(
        self,
        kb_id: str,
        query_text: str,
        limit: int = 10,
        version_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tokens = self._tokenize_query(query_text)
        if not tokens:
            return []
        token_like = [f"%{t}%" for t in tokens]
        where_token = " OR ".join(
            ["LOWER(source_entity) LIKE ? OR LOWER(target_entity) LIKE ? OR LOWER(relation) LIKE ?" for _ in tokens]
        )
        params: List[Any] = [kb_id]
        if version_id:
            sql = f"""
                SELECT * FROM kb_graph_relation
                WHERE knowledge_base_id = ?
                  AND version_id = ?
                  AND ({where_token})
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
            """
            params.append(version_id)
        else:
            sql = f"""
                SELECT * FROM kb_graph_relation
                WHERE knowledge_base_id = ?
                  AND ({where_token})
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
            """
        for like in token_like:
            params.extend([like, like, like])
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
