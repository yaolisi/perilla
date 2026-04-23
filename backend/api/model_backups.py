"""
model.json 备份 API。前缀 /api/model-backups，与 /api/backup（数据库备份）区分。
"""
from typing import List, Optional, Dict, Any, cast

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.errors import raise_api_error
from core.backup.model_json import (
    create_backup,
    create_all_backups,
    list_backups,
    delete_backup,
    restore_backup,
    run_daily_snapshot,
    retention_dry_run,
    cleanup_retention,
    restore_batch,
    list_daily_manifests,
    read_daily_manifest,
)
from core.security.deps import require_authenticated_platform_admin

router = APIRouter(
    prefix="/api/model-backups",
    tags=["model-backups"],
    dependencies=[Depends(require_authenticated_platform_admin)],
)


class CreateBackupRequest(BaseModel):
    model_id: str = Field(..., description="模型 ID，如 local:qwen3-8b")
    reason: Optional[str] = Field(None, description="备份原因/备注")
    tags: Optional[List[str]] = Field(None, description="标签，如 ['manual', 'ui']")


class CreateAllBackupRequest(BaseModel):
    reason: Optional[str] = Field(None, description="全量备份原因")


class DeleteBackupRequest(BaseModel):
    backup_id: str = Field(..., description="要删除的备份 ID")


class RestoreBackupRequest(BaseModel):
    backup_id: str = Field(..., description="备份 ID，如 bkp_20260312_021501_a1b2")
    dry_run: bool = Field(False, description="仅校验不写入")


class RestoreBatchRequest(BaseModel):
    target_timestamp_utc: str = Field(..., description="目标时间点 ISO，如 2026-03-12T00:00:00Z")
    model_ids: Optional[List[str]] = Field(None, description="要恢复的模型 ID 列表，为空则全部")
    dry_run: bool = Field(False, description="仅预览不写入")


class CleanupRequest(BaseModel):
    dry_run: bool = Field(True, description="默认 true 仅报告，false 时实际删除")
    model_id: Optional[str] = Field(None, description="仅清理该模型，为空则全部")


@router.get("/status")
async def api_backup_status() -> Dict[str, Any]:
    """备份状态（阶段 2）：每日清单日期、最近全量等。"""
    manifests = list_daily_manifests()
    last_daily = manifests[0] if manifests else None
    return {
        "last_daily_manifest_date": last_daily,
        "daily_manifest_dates": manifests,
    }


@router.post("/create")
async def api_create_backup(body: CreateBackupRequest) -> Dict[str, Any]:
    """创建单模型备份（§13.1）。"""
    result = create_backup(
        body.model_id,
        reason=body.reason,
        tags=body.tags,
        source="api",
    )
    if not result.get("success"):
        raise_api_error(
            status_code=400,
            code="model_json_backup_failed",
            message=str(result.get("error", "backup failed")),
            details={"model_id": body.model_id},
        )
    return cast(Dict[str, Any], result)


@router.post("/create-all")
async def api_create_all_backups(body: CreateAllBackupRequest) -> Dict[str, Any]:
    """创建全量快照（§13.2）。"""
    result = create_all_backups(reason=body.reason, source="api")
    return cast(Dict[str, Any], result)


@router.get("")
async def api_list_backups(model_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """查询备份记录（§13.3）。支持按 model_id 过滤。"""
    if limit < 1 or limit > 500:
        limit = 50
    return cast(Dict[str, Any], list_backups(model_id=model_id, limit=limit))


@router.post("/delete")
async def api_delete_backup(body: DeleteBackupRequest) -> Dict[str, Any]:
    """删除指定备份的快照文件；索引追加 delete 事件用于审计。"""
    result = delete_backup(body.backup_id, source="api")
    if not result.get("success"):
        raise_api_error(
            status_code=400,
            code="model_json_backup_delete_failed",
            message=str(result.get("error", "delete failed")),
            details={"backup_id": body.backup_id},
        )
    return cast(Dict[str, Any], result)


@router.post("/restore")
async def api_restore_backup(body: RestoreBackupRequest) -> Dict[str, Any]:
    """恢复备份（§13.4）。dry_run=true 仅校验不写入；恢复前会对当前版本做保护性备份。"""
    result = restore_backup(
        body.backup_id,
        dry_run=body.dry_run,
        source="api",
    )
    if not result.get("success"):
        raise_api_error(
            status_code=400,
            code="model_json_backup_restore_failed",
            message=str(result.get("error", "restore failed")),
            details={"backup_id": body.backup_id},
        )
    return cast(Dict[str, Any], result)


@router.post("/restore-batch")
async def api_restore_batch(body: RestoreBatchRequest) -> Dict[str, Any]:
    """批量回滚（阶段 2）：将指定模型恢复到目标时间点前最近一次备份。"""
    result = restore_batch(
        body.target_timestamp_utc,
        model_ids=body.model_ids,
        dry_run=body.dry_run,
        source="api",
    )
    if not result.get("success"):
        raise_api_error(
            status_code=400,
            code="model_json_backup_batch_restore_failed",
            message=str(result.get("error", "batch restore failed")),
        )
    return cast(Dict[str, Any], result)


@router.get("/retention-dry-run")
async def api_retention_dry_run(model_id: Optional[str] = None) -> Dict[str, Any]:
    """保留策略 dry-run（阶段 2）：返回将被删除的快照列表，不实际删除。"""
    return cast(Dict[str, Any], retention_dry_run(model_id=model_id))


@router.post("/cleanup")
async def api_cleanup(body: CleanupRequest) -> Dict[str, Any]:
    """按保留策略清理快照（阶段 2）。dry_run 时仅返回报告。"""
    return cast(
        Dict[str, Any],
        cleanup_retention(dry_run=body.dry_run, model_id=body.model_id),
    )


@router.get("/daily-manifests/{date_yyyymmdd}")
async def api_get_daily_manifest(date_yyyymmdd: str) -> Dict[str, Any]:
    """获取指定日期的每日快照清单（阶段 2）。date 格式 yyyyMMdd（8 位数字）。"""
    if len(date_yyyymmdd) != 8 or not date_yyyymmdd.isdigit():
        raise_api_error(
            status_code=400,
            code="model_json_manifest_invalid_date",
            message="date_yyyymmdd must be 8 digits (yyyyMMdd)",
            details={"date_yyyymmdd": date_yyyymmdd},
        )
    manifest = read_daily_manifest(date_yyyymmdd)
    if manifest is None:
        raise_api_error(
            status_code=404,
            code="model_json_manifest_not_found",
            message="manifest not found",
            details={"date_yyyymmdd": date_yyyymmdd},
        )
    return cast(Dict[str, Any], manifest)
