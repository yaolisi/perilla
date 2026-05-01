"""
Knowledge Base API 端点
"""
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field, RootModel
from typing import Annotated, Dict, List, Literal, Optional
from pathlib import Path
import uuid
import shutil
import json
import hashlib
from log import logger
from api.errors import APIException, raise_api_error
from config.settings import settings
from core.knowledge.knowledge_base_store import KnowledgeBaseStore, KnowledgeBaseConfig
from core.knowledge.file_storage import FileStorage
from core.knowledge.indexer import KnowledgeBaseIndexer
from core.knowledge.status import DocumentStatus
from core.utils.user_context import get_user_id, UserAccessDeniedError, ResourceNotFoundError

router = APIRouter(prefix="/api", tags=["knowledge"])
MSG_KB_NOT_FOUND = "Knowledge base not found"
MSG_DOC_NOT_FOUND = "Document not found"
MSG_DOC_WRONG_KB = "Document does not belong to this knowledge base"
MSG_REQUEST_REQUIRED = "Request is required"

# 确定统一数据库路径
_db_path = (
    Path(__file__).resolve().parents[1] / "data" / "platform.db"
    if not settings.db_path
    else Path(settings.db_path)
)

# 初始化 KnowledgeBaseStore
_kb_store = KnowledgeBaseStore(
    KnowledgeBaseConfig(
        db_path=_db_path,
        embedding_dim=settings.memory_embedding_dim,
    )
)


class KnowledgeJsonMap(BaseModel):
    """知识库 API 中的 disk_size、chunk metadata 等自由 JSON 对象。"""

    model_config = ConfigDict(extra="allow")


class KnowledgeStringIntMap(RootModel[Dict[str, int]]):
    """字符串键到整数的映射（如 chunk_size_overrides、文档状态计数）。"""


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: Optional[str] = None
    embedding_model_id: str
    chunk_size: int = 512
    chunk_overlap: int = 50
    chunk_size_overrides: KnowledgeStringIntMap = Field(default_factory=lambda: KnowledgeStringIntMap({}))


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: Optional[float] = None
    version_id: Optional[str] = None
    version_label: Optional[str] = None


class CreateKnowledgeBaseVersionRequest(BaseModel):
    version_label: str
    notes: Optional[str] = None


class GraphSearchRequest(BaseModel):
    query: str
    top_k: int = 10
    version_id: Optional[str] = None


# --- Response models (OpenAPI named schemas) ---


class KnowledgeBaseCreatedResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    embedding_model_id: str
    chunk_size: int
    chunk_overlap: int
    chunk_size_overrides: KnowledgeStringIntMap = Field(default_factory=lambda: KnowledgeStringIntMap({}))


class KnowledgeBaseRecordResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: Optional[str] = None
    embedding_model_id: str
    status: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    chunk_size_overrides_json: Optional[str] = None
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    disk_size: Optional[KnowledgeJsonMap] = None


class KnowledgeBaseListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[KnowledgeBaseRecordResponse]


class KnowledgeBaseDeleteResponse(BaseModel):
    deleted: bool = True
    id: str


class EmbeddingModelInfo(BaseModel):
    id: str
    name: str
    embedding_dim: int


class EmbeddingModelListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[EmbeddingModelInfo]


class KnowledgeBaseStatsResponse(BaseModel):
    knowledge_base_id: str
    document_count: int
    document_status_breakdown: KnowledgeStringIntMap
    chunk_count: int
    vector_count: int
    disk_size: KnowledgeJsonMap
    embedding_model_id: str


class KnowledgeDocumentRecordResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_base_id: str
    source: str
    doc_type: Optional[str] = None
    status: str = "UPLOADED"
    chunks_count: Optional[int] = 0
    chunks: Optional[int] = None
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    content_hash: Optional[str] = None
    current_version_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    user_id: Optional[str] = None


class KnowledgeDocumentListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[KnowledgeDocumentRecordResponse]


class DocumentUploadResponse(BaseModel):
    id: str
    knowledge_base_id: str
    source: str
    status: str


class DocumentDeleteResponse(BaseModel):
    deleted: bool = True
    id: str


class DocumentReindexResponse(BaseModel):
    id: str
    knowledge_base_id: str
    status: str
    message: str


class KnowledgeChunkItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    document_id: str
    content: str
    index: int
    metadata: Optional[KnowledgeJsonMap] = None


class KnowledgeChunkListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[KnowledgeChunkItem]
    total: int


class KnowledgeSearchHit(BaseModel):
    content: str
    distance: Optional[float] = None
    score: float
    version_id: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    doc_source: Optional[str] = None


class KnowledgeSearchResponse(BaseModel):
    object: Literal["list"] = "list"
    data: List[KnowledgeSearchHit]


class KbVersionCreatedResponse(BaseModel):
    id: str
    knowledge_base_id: str
    version_label: str
    notes: Optional[str] = None


class KbVersionRecordResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    version_label: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None


class KbVersionListEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[KbVersionRecordResponse]


class KnowledgeGraphRelationRow(BaseModel):
    """图谱检索行（字段依抽取结果变化；允许部分字段缺失）。"""

    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    version_id: Optional[str] = None
    source_entity: Optional[str] = None
    relation: Optional[str] = None
    target_entity: Optional[str] = None
    confidence: Optional[float] = None
    source_doc_id: Optional[str] = None
    created_at: Optional[str] = None


class KnowledgeGraphSearchEnvelope(BaseModel):
    object: Literal["list"] = "list"
    data: List[KnowledgeGraphRelationRow]


@router.post("/knowledge-bases", response_model=KnowledgeBaseCreatedResponse)
async def create_knowledge_base(req: CreateKnowledgeBaseRequest, request: Request) -> KnowledgeBaseCreatedResponse:
    """创建知识库"""
    try:
        user_id = get_user_id(request)
        
        kb_id = _kb_store.create_knowledge_base(
            name=req.name,
            description=req.description,
            embedding_model_id=req.embedding_model_id,
            user_id=user_id,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            chunk_size_overrides_json=json.dumps(
                req.chunk_size_overrides.model_dump(mode="json"),
                ensure_ascii=False,
            ),
        )
        return KnowledgeBaseCreatedResponse(
            id=kb_id,
            name=req.name,
            description=req.description,
            embedding_model_id=req.embedding_model_id,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            chunk_size_overrides=req.chunk_size_overrides,
        )
    except Exception as e:
        logger.error(f"Failed to create knowledge base: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases", response_model=KnowledgeBaseListEnvelope)
async def list_knowledge_bases(request: Request) -> KnowledgeBaseListEnvelope:
    """列出用户的所有知识库"""
    try:
        user_id = get_user_id(request)
        kbs = _kb_store.list_knowledge_bases(user_id=user_id)
        return KnowledgeBaseListEnvelope(
            object="list",
            data=[KnowledgeBaseRecordResponse.model_validate(k) for k in kbs],
        )
    except Exception as e:
        logger.error(f"Failed to list knowledge bases: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseRecordResponse)
async def get_knowledge_base(kb_id: str, request: Request) -> KnowledgeBaseRecordResponse:
    """获取知识库信息"""
    try:
        user_id = get_user_id(request)
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        assert kb is not None
        
        # 计算磁盘使用量
        disk_size_info = _kb_store.get_knowledge_base_disk_size(kb_id)
        kb["disk_size"] = disk_size_info

        return KnowledgeBaseRecordResponse.model_validate(kb)
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get knowledge base: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


class UpdateKnowledgeBaseRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    chunk_size_overrides: Optional[KnowledgeStringIntMap] = None


@router.patch("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseRecordResponse)
async def update_knowledge_base(
    kb_id: str,
    req: UpdateKnowledgeBaseRequest,
    request: Request,
) -> KnowledgeBaseRecordResponse:
    """更新知识库信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        assert kb is not None
        
        # 更新知识库
        success = _kb_store.update_knowledge_base(
            kb_id=kb_id,
            name=req.name,
            description=req.description,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            chunk_size_overrides_json=(
                json.dumps(req.chunk_size_overrides.model_dump(mode="json"), ensure_ascii=False)
                if req.chunk_size_overrides is not None
                else None
            ),
        )
        
        if not success:
            raise_api_error(
                status_code=500,
                code="knowledge_base_update_failed",
                message="Failed to update knowledge base",
                details={"knowledge_base_id": kb_id},
            )
        
        # 返回更新后的知识库信息
        updated_kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        assert updated_kb is not None
        return KnowledgeBaseRecordResponse.model_validate(updated_kb)
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to update knowledge base: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.delete("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseDeleteResponse)
async def delete_knowledge_base(kb_id: str, request: Request) -> KnowledgeBaseDeleteResponse:
    """删除知识库（包含物理文件删除）"""
    try:
        user_id = get_user_id(request)
        
        # 获取知识库下的所有文档，用于删除物理文件
        # 先获取 KB 信息（可能抛出权限或不存在异常）
        _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        
        # 删除所有文档的物理文件
        for doc in docs:
            if doc.get("file_path"):
                try:
                    file_path = Path(doc["file_path"])
                    if file_path.exists():
                        file_path.unlink()
                        logger.info(f"Deleted file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete file {doc.get('file_path')}: {e}")
        
        # 删除知识库目录（如果存在）
        try:
            kb_storage_dir = FileStorage.get_kb_storage_path(kb_id).parent  # parent 是 kb_id 目录
            if kb_storage_dir.exists():
                shutil.rmtree(kb_storage_dir)
                logger.info(f"Deleted knowledge base directory: {kb_storage_dir}")
        except Exception as e:
            logger.warning(f"Failed to delete knowledge base directory: {e}")
        
        # 删除数据库记录（级联删除文档和 chunks）
        _kb_store.delete_knowledge_base(kb_id, user_id=user_id)
        
        logger.info(f"Deleted knowledge base: {kb_id}")
        return KnowledgeBaseDeleteResponse(deleted=True, id=kb_id)
    except UserAccessDeniedError as e:
        logger.warning(f"Access denied: {e}")
        raise_api_error(status_code=403, code="knowledge_access_denied", message=str(e))
        raise AssertionError("unreachable")
    except ResourceNotFoundError as e:
        raise_api_error(status_code=404, code="knowledge_resource_not_found", message=str(e))
        raise AssertionError("unreachable")
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete knowledge base: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/models/embedding", response_model=EmbeddingModelListEnvelope)
async def list_embedding_models() -> EmbeddingModelListEnvelope:
    """列出所有 embedding 模型"""
    try:
        from core.models.registry import get_model_registry
        registry = get_model_registry()
        all_models = registry.list_models()
        
        # 过滤出 embedding 模型
        embedding_models = [
            EmbeddingModelInfo(
                id=m.id,
                name=m.name,
                embedding_dim=int(m.metadata.get("embedding_dim", 512)),
            )
            for m in all_models
            if m.model_type == "embedding"
        ]

        return EmbeddingModelListEnvelope(object="list", data=embedding_models)
    except Exception as e:
        logger.error(f"Failed to list embedding models: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases/{kb_id}/stats", response_model=KnowledgeBaseStatsResponse)
async def get_knowledge_base_stats(kb_id: str, request: Request) -> KnowledgeBaseStatsResponse:
    """获取知识库统计信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        assert kb is not None
        
        # 获取文档统计
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        doc_count = len(docs)
        
        # 按状态统计文档
        status_counts: Dict[str, int] = {}
        for doc in docs:
            status = doc.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # 获取 chunk 统计
        chunk_count = _kb_store.get_chunk_count(kb_id)
        
        # 获取磁盘使用量
        disk_size_info = _kb_store.get_knowledge_base_disk_size(kb_id)
        
        return KnowledgeBaseStatsResponse(
            knowledge_base_id=kb_id,
            document_count=doc_count,
            document_status_breakdown=KnowledgeStringIntMap(status_counts),
            chunk_count=chunk_count,
            vector_count=chunk_count,
            disk_size=KnowledgeJsonMap.model_validate(disk_size_info),
            embedding_model_id=str(kb["embedding_model_id"]),
        )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get knowledge base stats: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases/{kb_id}/documents", response_model=KnowledgeDocumentListEnvelope)
async def list_documents(kb_id: str, request: Request) -> KnowledgeDocumentListEnvelope:
    """列出知识库下的所有文档"""
    try:
        user_id = get_user_id(request)
        docs = _kb_store.list_documents(kb_id, user_id=user_id)
        # 确保状态和 chunks 字段存在
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            doc["status"] = doc.get("status", "UPLOADED")
            doc["chunks"] = doc.get("chunks_count", 0)
        return KnowledgeDocumentListEnvelope(
            object="list",
            data=[KnowledgeDocumentRecordResponse.model_validate(d) for d in docs if isinstance(d, dict)],
        )
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}", response_model=KnowledgeDocumentRecordResponse)
async def get_document(kb_id: str, doc_id: str, request: Request) -> KnowledgeDocumentRecordResponse:
    """获取文档详细信息"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        
        # 获取文档信息
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise_api_error(
                status_code=404,
                code="knowledge_document_not_found",
                message=MSG_DOC_NOT_FOUND,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        assert doc is not None
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise_api_error(
                status_code=400,
                code="knowledge_document_wrong_kb",
                message=MSG_DOC_WRONG_KB,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        
        # 添加额外统计信息
        doc["status"] = doc.get("status", "UPLOADED")
        doc["chunks"] = doc.get("chunks_count", 0)

        return KnowledgeDocumentRecordResponse.model_validate(doc)
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


def index_document_background(
    kb_id: str,
    doc_id: str,
    file_path: Path,
    doc_type: Optional[str],
    content_hash: Optional[str] = None,
    version_id: Optional[str] = None,
) -> None:
    """后台索引任务（同步函数，由 BackgroundTasks 调用）"""
    try:
        # 获取知识库信息，确保使用正确的 embedding 维度
        kb_info = _kb_store.get_knowledge_base(kb_id)
        if not kb_info:
            raise ValueError(f"Knowledge base '{kb_id}' not found")
        
        # 从 embedding model 获取正确的维度
        from core.models.registry import get_model_registry
        model_registry = get_model_registry()
        embedding_model = model_registry.get_model(kb_info["embedding_model_id"])
        if embedding_model:
            actual_embedding_dim = embedding_model.metadata.get("embedding_dim", 512)
            # 更新 KnowledgeBaseStore 的配置
            if _kb_store.config.embedding_dim != actual_embedding_dim:
                logger.info(
                    f"[Indexer] Updating embedding_dim from {_kb_store.config.embedding_dim} "
                    f"to {actual_embedding_dim} for KB {kb_id}"
                )
                _kb_store.config.embedding_dim = actual_embedding_dim

            # Ensure vec0 table dimension matches (may recreate table)
            _kb_store._ensure_vec_table_dimension(kb_id, actual_embedding_dim)
        
        kb_chunk_size = int(kb_info.get("chunk_size") or 500)
        kb_chunk_overlap = int(kb_info.get("chunk_overlap") or 50)
        kb_overrides_raw = kb_info.get("chunk_size_overrides_json") or "{}"
        try:
            kb_overrides = json.loads(kb_overrides_raw)
        except Exception:
            kb_overrides = {}
        effective_chunk_size = kb_chunk_size
        doc_type_key = (doc_type or "").lower()
        if isinstance(kb_overrides, dict) and doc_type_key:
            override_size = kb_overrides.get(doc_type_key)
            if isinstance(override_size, (int, float)):
                effective_chunk_size = int(override_size)
        indexer = KnowledgeBaseIndexer(_kb_store, chunk_size=effective_chunk_size, chunk_overlap=kb_chunk_overlap)
        result = indexer.index_document(
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=doc_type,
            version_id=version_id,
        )
        
        # 更新文档状态
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=result["status"],
            chunks_count=result.get("chunks_created", 0),
            error_message=result.get("error"),
        )
        if result["status"] == DocumentStatus.INDEXED:
            if content_hash:
                _kb_store.update_document_content_hash(doc_id, content_hash)
            resolved_version_id = version_id or _kb_store.ensure_default_kb_version(kb_id)
            _kb_store.add_document_version(
                document_id=doc_id,
                knowledge_base_id=kb_id,
                version_id=resolved_version_id,
                content_hash=content_hash,
            )
        logger.info(f"Background indexing completed for {doc_id}: {result['status']}")
    except Exception as e:
        logger.error(f"Background indexing failed for {doc_id}: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=DocumentStatus.FAILED_EMBED,
            error_message=str(e),
        )


@router.post("/knowledge-bases/{kb_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    kb_id: str,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    request: Request,
) -> DocumentUploadResponse:
    """上传文档到知识库并启动索引流程"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        
        # 验证文件类型
        allowed_extensions = {'.pdf', '.txt', '.md', '.docx'}
        if not file.filename:
            raise_api_error(status_code=400, code="knowledge_upload_filename_required", message="Filename is required")
        
        filename = file.filename
        assert filename is not None
        file_ext = Path(filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise_api_error(
                status_code=400,
                code="knowledge_upload_unsupported_type",
                message=f"Unsupported file type: {file_ext}. Supported types: PDF, TXT, MD, DOCX",
                details={"file_ext": file_ext},
            )
        
        # 验证文件大小（20MB）
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise_api_error(
                status_code=400,
                code="knowledge_upload_file_too_large",
                message="File size exceeds 20MB limit",
            )
        
        # 创建文档记录
        content_hash = hashlib.sha256(content).hexdigest()
        version_id = _kb_store.ensure_default_kb_version(kb_id)
        doc_id = _kb_store.create_document(
            knowledge_base_id=kb_id,
            source=filename,
            doc_type=file_ext[1:] if file_ext else None,
            status=DocumentStatus.UPLOADED,
            user_id=user_id,
            content_hash=content_hash,
        )
        
        # 保存文件到本地存储
        file_path = FileStorage.save_file(kb_id, doc_id, content, filename)
        _kb_store.update_document_file_path(doc_id, str(file_path))
        _kb_store.update_document_status(doc_id, DocumentStatus.UPLOADED)
        
        # 使用 BackgroundTasks 启动索引流程（不阻塞响应）
        background_tasks.add_task(
            index_document_background,
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=file_ext[1:] if file_ext else None,
            content_hash=content_hash,
            version_id=version_id,
        )
        
        logger.info(f"Document uploaded: {doc_id} to KB {kb_id}, indexing started")
        
        return DocumentUploadResponse(
            id=doc_id,
            knowledge_base_id=kb_id,
            source=filename,
            status=str(DocumentStatus.UPLOADED),
        )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload document: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}", response_model=DocumentDeleteResponse)
async def delete_document(kb_id: str, doc_id: str, request: Request) -> DocumentDeleteResponse:
    """删除文档"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        
        # 获取文档信息（用于删除文件）
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise_api_error(
                status_code=404,
                code="knowledge_document_not_found",
                message=MSG_DOC_NOT_FOUND,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        assert doc is not None
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise_api_error(
                status_code=400,
                code="knowledge_document_wrong_kb",
                message=MSG_DOC_WRONG_KB,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        
        # 删除 chunks（通过知识库的向量表）
        _kb_store.delete_document_chunks(kb_id, doc_id)
        
        # 删除文件（如果存在）
        if doc.get("file_path"):
            try:
                from pathlib import Path
                file_path = Path(doc["file_path"])
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Deleted file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete file {doc['file_path']}: {e}")
        
        # 删除文档记录
        success = _kb_store.delete_document(doc_id, user_id=user_id)
        
        if not success:
            raise_api_error(
                status_code=404,
                code="knowledge_document_not_found",
                message=MSG_DOC_NOT_FOUND,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        
        logger.info(f"Deleted document: {doc_id} from KB {kb_id}")
        
        return DocumentDeleteResponse(deleted=True, id=doc_id)
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex", response_model=DocumentReindexResponse)
async def reindex_document(
    kb_id: str,
    doc_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    force: bool = False,
) -> DocumentReindexResponse:
    """重新索引文档"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        
        # 获取文档信息
        doc = _kb_store.get_document(doc_id)
        if not doc:
            raise_api_error(
                status_code=404,
                code="knowledge_document_not_found",
                message=MSG_DOC_NOT_FOUND,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        assert doc is not None
        
        # 验证文档属于该知识库
        if doc["knowledge_base_id"] != kb_id:
            raise_api_error(
                status_code=400,
                code="knowledge_document_wrong_kb",
                message=MSG_DOC_WRONG_KB,
                details={"document_id": doc_id, "knowledge_base_id": kb_id},
            )
        
        # 验证文件存在
        if not doc.get("file_path"):
            raise_api_error(
                status_code=400,
                code="knowledge_document_no_file_path",
                message="Document file path not found",
                details={"document_id": doc_id},
            )

        file_path = Path(doc["file_path"])
        if not file_path.exists():
            raise_api_error(
                status_code=400,
                code="knowledge_document_file_missing",
                message=f"Document file not found: {file_path}",
                details={"document_id": doc_id, "path": str(file_path)},
            )

        # 增量更新：hash 未变化则跳过（除非 force=true）
        content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if not force and not _kb_store.should_reindex_document(doc_id, content_hash):
            return DocumentReindexResponse(
                id=doc_id,
                knowledge_base_id=kb_id,
                status=str(doc.get("status", DocumentStatus.INDEXED)),
                message="Skipped re-indexing: no content change detected",
            )
        
        # 1. 删除旧的 chunks
        logger.info(f"Deleting old chunks for document {doc_id}")
        _kb_store.delete_document_chunks(kb_id, doc_id)
        
        # 2. 重置文档状态
        _kb_store.update_document_status(
            doc_id=doc_id,
            status=DocumentStatus.UPLOADED,
            chunks_count=0,
            error_message=None,
        )
        
        # 3. 启动后台索引任务
        background_tasks.add_task(
            index_document_background,
            kb_id=kb_id,
            doc_id=doc_id,
            file_path=file_path,
            doc_type=doc.get("doc_type"),
            content_hash=content_hash,
            version_id=_kb_store.ensure_default_kb_version(kb_id),
        )
        
        logger.info(f"Re-indexing started for document {doc_id}")
        
        return DocumentReindexResponse(
            id=doc_id,
            knowledge_base_id=kb_id,
            status=str(DocumentStatus.UPLOADED),
            message="Re-indexing started",
        )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to re-index document: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.get("/knowledge-bases/{kb_id}/chunks", response_model=KnowledgeChunkListEnvelope)
async def list_chunks(
    kb_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    document_id: Optional[str] = None,
) -> KnowledgeChunkListEnvelope:
    """列出知识库下的所有 chunks"""
    try:
        user_id = get_user_id(request)

        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        
        # 获取 chunk 数量
        total = _kb_store.get_chunk_count(kb_id)
        
        # 查询 chunks
        chunks = _kb_store.list_chunks(
            knowledge_base_id=kb_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
        
        return KnowledgeChunkListEnvelope(
            object="list",
            data=[KnowledgeChunkItem.model_validate(c) for c in chunks],
            total=total,
        )
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to list chunks: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.post("/knowledge-bases/{kb_id}/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_base(
    kb_id: str,
    req: SearchRequest,
    request: Request,
) -> KnowledgeSearchResponse:
    """检索知识库"""
    try:
        user_id = get_user_id(request)
        
        # 验证知识库存在
        kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
        if not kb:
            raise_api_error(
                status_code=404,
                code="knowledge_base_not_found",
                message=MSG_KB_NOT_FOUND,
                details={"knowledge_base_id": kb_id},
            )
        assert kb is not None
        
        # 获取 embedding model
        from core.models.registry import get_model_registry
        registry = get_model_registry()
        embedding_model = registry.get_model(kb["embedding_model_id"])
        if not embedding_model:
            mid = kb["embedding_model_id"]
            raise_api_error(
                status_code=500,
                code="knowledge_embedding_model_not_found",
                message=f"Embedding model '{mid}' not found",
                details={"embedding_model_id": mid, "knowledge_base_id": kb_id},
            )
        assert embedding_model is not None
        
        # 从 embedding model 获取实际维度
        actual_embedding_dim = embedding_model.metadata.get("embedding_dim", settings.memory_embedding_dim)
        
        # 使用正确的维度创建 KnowledgeBaseStore 实例
        # 注意：每个知识库有独立的向量表，这里只需要确保该知识库的表存在
        kb_store = KnowledgeBaseStore(
            KnowledgeBaseConfig(
                db_path=_db_path,
                embedding_dim=actual_embedding_dim,
            )
        )
        # 确保知识库的向量表存在且维度正确
        kb_store._ensure_vec_table_dimension(kb_id, actual_embedding_dim)
        
        # 生成 query embedding（通过 Inference Gateway 解耦调用方）
        from core.inference import get_inference_client
        client = get_inference_client()
        embed_resp = await client.embed(
            model=embedding_model.id,
            input_text=[req.query],
            metadata={
                "caller": "api.knowledge.search",
                "kb_id": kb_id,
                "user_id": user_id,
            },
        )
        query_embeddings = embed_resp.embeddings
        if not query_embeddings:
            raise_api_error(
                status_code=500,
                code="knowledge_search_embedding_failed",
                message="Failed to generate query embedding",
                details={"knowledge_base_id": kb_id},
            )
        
        query_embedding = query_embeddings[0]
        
        # 验证 query embedding 维度
        if len(query_embedding) != actual_embedding_dim:
            raise_api_error(
                status_code=500,
                code="knowledge_search_embedding_dimension_mismatch",
                message=(
                    f"Query embedding dimension mismatch: expected {actual_embedding_dim}, "
                    f"got {len(query_embedding)}"
                ),
                details={
                    "knowledge_base_id": kb_id,
                    "expected_dim": actual_embedding_dim,
                    "actual_dim": len(query_embedding),
                },
            )
        
        resolved_version_id = kb_store.resolve_kb_version_id(
            kb_id=kb_id,
            version_id=req.version_id,
            version_label=req.version_label,
        )

        # 向量检索
        results = kb_store.search_chunks(
            knowledge_base_id=kb_id,
            query_embedding=query_embedding,
            limit=req.top_k,
            max_distance=req.score_threshold,
            version_id=resolved_version_id,
        )
        
        hits = [
            KnowledgeSearchHit(
                content=item.get("content", ""),
                distance=item.get("distance"),
                score=1.0 - float(item.get("distance", 1.0)),
                version_id=item.get("version_id"),
                document_id=item.get("document_id"),
                chunk_id=item.get("chunk_id"),
                doc_source=item.get("doc_source"),
            )
            for item in results
        ]
        return KnowledgeSearchResponse(object="list", data=hits)
    except APIException:
        raise
    except Exception as e:
        logger.error(f"Failed to search knowledge base: {e}", exc_info=True)
        raise_api_error(status_code=500, code="knowledge_internal_error", message=str(e))
        raise AssertionError("unreachable")


@router.post("/knowledge-bases/{kb_id}/versions", response_model=KbVersionCreatedResponse)
async def create_kb_version(
    kb_id: str,
    req: CreateKnowledgeBaseVersionRequest,
    request: Request,
) -> KbVersionCreatedResponse:
    user_id = get_user_id(request)
    kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
    if not kb:
        raise_api_error(status_code=404, code="knowledge_base_not_found", message=MSG_KB_NOT_FOUND)
    version_id = _kb_store.create_kb_version(
        kb_id=kb_id,
        version_label=req.version_label,
        notes=req.notes,
        status="ACTIVE",
    )
    return KbVersionCreatedResponse(
        id=version_id,
        knowledge_base_id=kb_id,
        version_label=req.version_label,
        notes=req.notes,
    )


@router.get("/knowledge-bases/{kb_id}/versions", response_model=KbVersionListEnvelope)
async def list_kb_versions(kb_id: str, request: Request) -> KbVersionListEnvelope:
    user_id = get_user_id(request)
    kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
    if not kb:
        raise_api_error(status_code=404, code="knowledge_base_not_found", message=MSG_KB_NOT_FOUND)
    versions = _kb_store.list_kb_versions(kb_id)
    return KbVersionListEnvelope(
        object="list",
        data=[KbVersionRecordResponse.model_validate(v) for v in versions],
    )


@router.post("/knowledge-bases/{kb_id}/graph/search", response_model=KnowledgeGraphSearchEnvelope)
async def search_kb_graph(
    kb_id: str,
    req: GraphSearchRequest,
    request: Request,
) -> KnowledgeGraphSearchEnvelope:
    user_id = get_user_id(request)
    kb = _kb_store.get_knowledge_base(kb_id, user_id=user_id)
    if not kb:
        raise_api_error(status_code=404, code="knowledge_base_not_found", message=MSG_KB_NOT_FOUND)
    results = _kb_store.search_graph_relations(
        kb_id=kb_id,
        query_text=req.query,
        limit=req.top_k,
        version_id=req.version_id,
    )
    return KnowledgeGraphSearchEnvelope(
        object="list",
        data=[KnowledgeGraphRelationRow.model_validate(r) for r in results],
    )
