"""
Image generation API.

Supports:
- synchronous generation
- async job mode with polling
"""

import asyncio
import base64
import binascii
import contextvars
import gc
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable, Dict, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.engine import Engine
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from log import logger
from api.errors import APIException, raise_api_error
from config.settings import settings
from core.utils.tenant_request import resolve_api_tenant_id
from core.data.base import get_db, get_engine, sessionmaker_for_engine
from core.data.models.image_generation import ImageGenerationJobORM, ImageGenerationWarmupORM
from core.models.descriptor import ModelDescriptor
from core.models.registry import get_model_registry
from core.runtime.queue import get_inference_queue_manager
from core.runtimes.factory import get_runtime_factory
from core.runtimes.image_generation_types import (
    ImageGenerationJobDeleteResponse,
    ImageGenerationJobResponse,
    ImageGenerationJobListResponse,
    ImageGenerationJobStatus,
    ImageGenerationRequest as RuntimeImageGenerationRequest,
    ImageGenerationResponse,
    ImageGenerationWarmupCompletedResponse,
    ImageGenerationWarmupResponse,
)

router = APIRouter()
DEFAULT_IMAGE_MIME = "image/png"
JOB_CANCELLED_MSG = "Image generation job cancelled"
JOB_CANCELLED_BEFORE_START_MSG = "Image generation job cancelled before start"


async def _require_image_job_tenant(job_id: str, tid: str, db: Session) -> None:
    j = await _get_job(job_id)
    if j is not None:
        if (str(j.tenant_id).strip() or "default") != tid:
            _raise_job_not_found(job_id)
        return
    row = db.get(ImageGenerationJobORM, job_id)
    if row is None:
        return
    if (str(getattr(row, "tenant_id", None) or "").strip() or "default") != tid:
        _raise_job_not_found(job_id)


class ImageGenerateRequest(BaseModel):
    model: str = Field(..., description="image_generation 模型 ID")
    prompt: str = Field(..., min_length=1, description="正向提示词")
    negative_prompt: str | None = Field(default=None, description="负向提示词")
    width: int | None = Field(default=None, ge=64, le=4096)
    height: int | None = Field(default=None, ge=64, le=4096)
    num_inference_steps: int | None = Field(default=None, ge=1, le=200)
    guidance_scale: float | None = Field(default=None, ge=0, le=50)
    seed: int | None = Field(default=None, ge=0)
    image_format: str = Field(default="PNG", description="输出格式，如 PNG/JPEG")


class ImageWarmupRequest(BaseModel):
    model: str = Field(..., description="image_generation 模型 ID")
    prompt: str = Field(default="warmup image", min_length=1, description="warmup 用提示词")
    width: int = Field(default=256, ge=64, le=1024)
    height: int = Field(default=256, ge=64, le=1024)
    num_inference_steps: int = Field(default=1, ge=1, le=8)
    guidance_scale: float = Field(default=1.0, ge=0, le=20)
    seed: int = Field(default=42, ge=0)


@dataclass
class _ImageGenerationJob:
    job_id: str
    request: ImageGenerateRequest
    status: ImageGenerationJobStatus
    created_at: datetime
    tenant_id: str = "default"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    phase: Optional[str] = None
    queue_position: Optional[int] = None
    error: Optional[str] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    progress: Optional[float] = None
    result: Optional[ImageGenerationResponse] = None
    cancelled: bool = False
    task: Optional[asyncio.Task] = field(default=None, repr=False)


_IMAGE_JOBS: Dict[str, _ImageGenerationJob] = {}
_IMAGE_JOBS_LOCK = asyncio.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GENERATED_IMAGES_DIR = (_PROJECT_ROOT / "backend" / "data" / "generated_images").resolve()

# 异步任务创建时由 generate_image(wait=false) 设置，使 to_thread 落库与 Depends(get_db) 同引擎（含测试 override）
_image_store_bind: contextvars.ContextVar[Optional[Engine]] = contextvars.ContextVar(
    "_image_store_bind", default=None
)


def _open_image_db_session() -> Session:
    """后台 to_thread / 队列任务用短生命周期 Session；若上下文已设置 bind 则与当前请求的 get_db 对齐。"""
    bind = _image_store_bind.get()
    if bind is not None:
        return sessionmaker_for_engine(bind)()
    return sessionmaker_for_engine(get_engine())()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clone_request(request: ImageGenerateRequest) -> ImageGenerateRequest:
    return cast(ImageGenerateRequest, ImageGenerateRequest.model_validate(request.model_dump()))


def _is_mps_oom_error(exc: Exception) -> bool:
    text = str(exc or "")
    lowered = text.lower()
    return "mps backend out of memory" in lowered or (
        "out of memory" in lowered and "mps" in lowered
    )


async def _force_release_other_image_generation_runtimes(
    factory: Any,
    *,
    keep_model_id: Optional[str] = None,
    reason: str = "",
) -> int:
    keep = {keep_model_id} if keep_model_id else set()
    released = await factory.unload_other_image_generation_runtimes(keep_model_ids=keep)
    gc.collect()
    try:
        import torch  # type: ignore

        if hasattr(torch, "mps"):
            torch.mps.empty_cache()
    except Exception:
        pass
    if released > 0:
        logger.info(
            "[ImageGenerateAPI] released_other_image_runtimes released=%s keep=%s reason=%s",
            released,
            keep_model_id or "-",
            reason or "n/a",
        )
    return cast(int, released)


def _db_upsert_job(job: _ImageGenerationJob) -> None:
    db: Session = _open_image_db_session()
    try:
        row = db.get(ImageGenerationJobORM, job.job_id)
        payload = {
            "job_id": job.job_id,
            "tenant_id": (str(getattr(job, "tenant_id", None) or "").strip() or "default"),
            "model": job.request.model,
            "prompt": job.request.prompt,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "phase": job.phase,
            "error": job.error,
            "request_json": {
                **job.request.model_dump(mode="json"),
                "__queue_position": job.queue_position,
                "__current_step": job.current_step,
                "__total_steps": job.total_steps,
                "__progress": job.progress,
            },
            "result_json": job.result.model_dump(mode="json") if job.result else None,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }
        if row is None:
            row = ImageGenerationJobORM(**payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.commit()
    finally:
        db.close()


def _db_delete_job(job_id: str) -> None:
    db: Session = _open_image_db_session()
    try:
        row = db.get(ImageGenerationJobORM, job_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


def _db_mark_warmups_not_latest(model: str, *, tenant_id: str = "default") -> None:
    tid = (str(tenant_id).strip() or "default")
    db: Session = _open_image_db_session()
    try:
        db.query(ImageGenerationWarmupORM).filter(
            ImageGenerationWarmupORM.tenant_id == tid,
            ImageGenerationWarmupORM.model == model,
            ImageGenerationWarmupORM.latest.is_(True),
        ).update({"latest": False}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _db_create_warmup(
    *,
    warmup_id: str,
    model: str,
    prompt: str,
    request_json: dict,
    started_at: datetime,
    finished_at: datetime,
    elapsed_ms: int,
    output_path: Optional[str],
    width: Optional[int],
    height: Optional[int],
    result_json: Optional[dict],
    status: str = "succeeded",
    error: Optional[str] = None,
    tenant_id: str = "default",
) -> None:
    tid = (str(tenant_id).strip() or "default")
    db: Session = _open_image_db_session()
    try:
        db.query(ImageGenerationWarmupORM).filter(
            ImageGenerationWarmupORM.tenant_id == tid,
            ImageGenerationWarmupORM.model == model,
            ImageGenerationWarmupORM.latest.is_(True),
        ).update({"latest": False}, synchronize_session=False)
        row = ImageGenerationWarmupORM(
            warmup_id=warmup_id,
            tenant_id=tid,
            model=model,
            prompt=prompt,
            status=status,
            elapsed_ms=elapsed_ms,
            output_path=output_path,
            width=width,
            height=height,
            error=error,
            request_json=request_json,
            result_json=result_json,
            latest=True,
            created_at=started_at,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()


def _db_get_latest_warmup(model: Optional[str] = None, *, tenant_id: str = "default") -> Optional[ImageGenerationWarmupORM]:
    tid = (str(tenant_id).strip() or "default")
    db: Session = _open_image_db_session()
    try:
        query = db.query(ImageGenerationWarmupORM).filter(ImageGenerationWarmupORM.tenant_id == tid)
        if model:
            query = query.filter(ImageGenerationWarmupORM.model == model)
        row = query.order_by(ImageGenerationWarmupORM.created_at.desc()).first()
        if row is None:
            return None
        db.expunge(row)
        return row
    finally:
        db.close()


def _orm_to_job_response(row: ImageGenerationJobORM, *, include_base64: bool = True) -> ImageGenerationJobResponse:
    result = None
    if row.result_json:
        payload = dict(row.result_json)
        if not include_base64:
            payload["image_base64"] = ""
        result = ImageGenerationResponse.model_validate(payload)
    request_json = cast(Dict[str, Any], row.request_json or {})
    return ImageGenerationJobResponse(
        job_id=cast(str, row.job_id),
        status=ImageGenerationJobStatus(cast(str, row.status)),
        model=cast(str, row.model),
        prompt=cast(str, row.prompt),
        phase=cast(Optional[str], row.phase),
        error=cast(Optional[str], row.error),
        created_at=cast(datetime, row.created_at),
        started_at=cast(Optional[datetime], row.started_at),
        finished_at=cast(Optional[datetime], row.finished_at),
        queue_position=cast(Optional[int], request_json.get("__queue_position")),
        current_step=cast(Optional[int], request_json.get("__current_step")),
        total_steps=cast(Optional[int], request_json.get("__total_steps")),
        progress=cast(Optional[float], request_json.get("__progress")),
        result=result,
    )


def _orm_to_warmup_response(row: ImageGenerationWarmupORM) -> ImageGenerationWarmupResponse:
    return ImageGenerationWarmupResponse(
        warmup_id=cast(str, row.warmup_id),
        model=cast(str, row.model),
        status=cast(str, row.status),
        started_at=cast(Optional[datetime], row.started_at),
        finished_at=cast(Optional[datetime], row.finished_at),
        elapsed_ms=cast(Optional[int], row.elapsed_ms),
        output_path=cast(Optional[str], row.output_path),
        width=cast(Optional[int], row.width),
        height=cast(Optional[int], row.height),
        error=cast(Optional[str], row.error),
    )


def _image_extension_from_mime(mime_type: str) -> str:
    lower = (mime_type or "").lower()
    if lower == "image/jpeg":
        return "jpg"
    if lower == "image/webp":
        return "webp"
    return "png"


def _persist_image_result(response: ImageGenerationResponse, job_id: Optional[str]) -> ImageGenerationResponse:
    _GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    stem = job_id or f"img_{int(_utcnow().timestamp())}"
    ext = _image_extension_from_mime(response.mime_type)
    output_path = (_GENERATED_IMAGES_DIR / f"{stem}.{ext}").resolve()
    try:
        output_path.write_bytes(base64.b64decode(response.image_base64))
    except binascii.Error as e:
        raise_api_error(
            status_code=500,
            code="image_generation_persist_failed",
            message=f"Failed to persist generated image: {e}",
        )

    response.output_path = str(output_path)
    if job_id:
        response.download_url = f"/api/v1/images/jobs/{job_id}/file"
        try:
            from PIL import Image
            import io

            thumb_path = (_GENERATED_IMAGES_DIR / f"{stem}_thumb.{ext}").resolve()
            with Image.open(io.BytesIO(base64.b64decode(response.image_base64))) as image:
                image.thumbnail((256, 256))
                image.save(thumb_path, format=(response.mime_type.split("/")[-1] or "png").upper())
            response.thumbnail_path = str(thumb_path)
            response.thumbnail_url = f"/api/v1/images/jobs/{job_id}/thumbnail"
        except Exception as e:
            logger.warning("[ImageGenerateAPI] thumbnail_generation_failed job_id=%s err=%s", job_id, e)
    return response


def _ensure_thumbnail_for_payload(job_id: str, payload: dict) -> Optional[str]:
    thumbnail_path = payload.get("thumbnail_path")
    if isinstance(thumbnail_path, str) and thumbnail_path and Path(thumbnail_path).resolve().is_file():
        return thumbnail_path

    output_path = payload.get("output_path")
    mime_type = payload.get("mime_type") or DEFAULT_IMAGE_MIME
    if not output_path:
        return None

    source = Path(output_path).resolve()
    if not source.is_file():
        return None

    try:
        from PIL import Image

        ext = _image_extension_from_mime(mime_type)
        thumb_path = (_GENERATED_IMAGES_DIR / f"{job_id}_thumb.{ext}").resolve()
        with Image.open(source) as image:
            image.thumbnail((256, 256))
            image.save(thumb_path, format=(mime_type.split("/")[-1] or "png").upper())
        payload["thumbnail_path"] = str(thumb_path)
        payload["thumbnail_url"] = f"/api/v1/images/jobs/{job_id}/thumbnail"
        return str(thumb_path)
    except Exception as e:
        logger.warning("[ImageGenerateAPI] lazy_thumbnail_generation_failed job_id=%s err=%s", job_id, e)
        return None


async def _get_job(job_id: str) -> Optional[_ImageGenerationJob]:
    async with _IMAGE_JOBS_LOCK:
        return _IMAGE_JOBS.get(job_id)


async def _save_job(job: _ImageGenerationJob) -> None:
    async with _IMAGE_JOBS_LOCK:
        _IMAGE_JOBS[job.job_id] = job
    await asyncio.to_thread(_db_upsert_job, job)


async def _patch_job(job_id: str, **updates: Any) -> Optional[_ImageGenerationJob]:
    async with _IMAGE_JOBS_LOCK:
        job = _IMAGE_JOBS.get(job_id)
        if not job:
            return None
        for key, value in updates.items():
            setattr(job, key, value)
    await asyncio.to_thread(_db_upsert_job, job)
    return job


def _job_to_response(job: _ImageGenerationJob, *, include_base64: bool = True) -> ImageGenerationJobResponse:
    result = job.result
    if result is not None and not include_base64:
        payload = result.model_copy(deep=True)
        payload.image_base64 = ""
        result = payload
    return ImageGenerationJobResponse(
        job_id=job.job_id,
        status=job.status,
        model=job.request.model,
        prompt=job.request.prompt,
        phase=job.phase,
        error=job.error,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        queue_position=job.queue_position,
        current_step=job.current_step,
        total_steps=job.total_steps,
        progress=job.progress,
        result=result,
    )


async def _get_pending_count_for_model(model_id: str, *, tenant_id: str = "default") -> int:
    tid = (str(tenant_id).strip() or "default")
    async with _IMAGE_JOBS_LOCK:
        return sum(
            1
            for job in _IMAGE_JOBS.values()
            if job.tenant_id == tid
            and job.request.model == model_id
            and job.status in {ImageGenerationJobStatus.QUEUED, ImageGenerationJobStatus.RUNNING}
        )


async def _get_queued_count_for_model(model_id: str, *, tenant_id: str = "default") -> int:
    tid = (str(tenant_id).strip() or "default")
    async with _IMAGE_JOBS_LOCK:
        return sum(
            1
            for job in _IMAGE_JOBS.values()
            if job.tenant_id == tid
            and job.request.model == model_id
            and job.status == ImageGenerationJobStatus.QUEUED
        )


async def _recompute_queue_positions(model_id: str, tenant_id: str = "default") -> None:
    tid = (str(tenant_id).strip() or "default")
    async with _IMAGE_JOBS_LOCK:
        queued = [
            job
            for job in _IMAGE_JOBS.values()
            if job.tenant_id == tid
            and job.request.model == model_id
            and job.status == ImageGenerationJobStatus.QUEUED
        ]
        queued.sort(key=lambda item: item.created_at)
        updates = []
        for idx, job in enumerate(queued, start=1):
            if job.queue_position != idx:
                job.queue_position = idx
                updates.append(job)
    for job in updates:
        await asyncio.to_thread(_db_upsert_job, job)


def _row_to_response(
    row: ImageGenerationJobORM,
    *,
    include_result: bool,
    include_base64: bool = True,
) -> ImageGenerationJobResponse:
    payload = _orm_to_job_response(row, include_base64=include_base64)
    if not include_result:
        payload.result = None
    return payload


def _extract_result_paths(
    removed: Optional[_ImageGenerationJob],
    row: Optional[ImageGenerationJobORM],
) -> tuple[Optional[str], Optional[str]]:
    if removed and removed.result:
        return removed.result.output_path, removed.result.thumbnail_path
    row_payload = cast(Dict[str, Any], row.result_json or {}) if row else {}
    return row_payload.get("output_path"), row_payload.get("thumbnail_path")


def _is_running_job_status(status: str) -> bool:
    return status in {ImageGenerationJobStatus.QUEUED.value, ImageGenerationJobStatus.RUNNING.value}


def _raise_job_delete_conflict(job_id: str) -> None:
    raise_api_error(
        status_code=409,
        code="image_generation_job_delete_conflict",
        message="Cannot delete a running image generation job",
        details={"job_id": job_id},
    )


def _raise_job_not_found(job_id: str) -> None:
    raise_api_error(
        status_code=404,
        code="image_generation_job_not_found",
        message=f"Image generation job not found: {job_id}",
        details={"job_id": job_id},
    )


def _cleanup_generated_files(
    *,
    job_id: str,
    output_path: Optional[str],
    thumbnail_path: Optional[str],
) -> None:
    for candidate_path, label in ((output_path, "image"), (thumbnail_path, "thumbnail")):
        if not candidate_path:
            continue
        try:
            path_obj = Path(candidate_path).resolve()
            if path_obj.is_file():
                path_obj.unlink()
        except Exception:
            logger.warning(
                "[ImageGenerateAPI] Failed to delete generated %s for job_id=%s path=%s",
                label,
                job_id,
                candidate_path,
            )


def _raise_thumbnail_not_found(job_id: str) -> None:
    raise_api_error(
        status_code=404,
        code="image_generation_thumbnail_not_found",
        message=f"Generated thumbnail not found for job: {job_id}",
        details={"job_id": job_id},
    )


def _load_thumbnail_from_db(
    *,
    job_id: str,
    current_mime_type: Optional[str],
    db: Optional[Session] = None,
) -> tuple[Optional[str], Optional[str]]:
    thumb_path: Optional[str] = None
    mime_type: Optional[str] = current_mime_type
    own_session = db is None
    if own_session:
        db = _open_image_db_session()
    assert db is not None
    try:
        row = db.get(ImageGenerationJobORM, job_id)
        if not row or not row.result_json:
            _raise_thumbnail_not_found(job_id)
        assert row is not None
        payload = dict(row.result_json)
        thumb_path = _ensure_thumbnail_for_payload(job_id, payload)
        mime_type = payload.get("mime_type") or mime_type
        if thumb_path and payload != row.result_json:
            setattr(row, "result_json", payload)
            db.commit()
    finally:
        if own_session:
            db.close()
    return thumb_path, mime_type


def _validate_descriptor(request: ImageGenerateRequest) -> ModelDescriptor:
    registry = get_model_registry()
    descriptor = registry.get_model(request.model)
    if not descriptor:
        raise_api_error(
            status_code=404,
            code="image_generation_model_not_found",
            message=f"Model not found: {request.model}",
            details={"model_id": request.model},
        )
    assert descriptor is not None

    model_type = (getattr(descriptor, "model_type", "") or "").lower()
    if model_type != "image_generation":
        raise_api_error(
            status_code=400,
            code="image_generation_model_wrong_type",
            message=(
                f"Model {request.model} is not an image_generation model "
                f"(model_type={descriptor.model_type})"
            ),
            details={"model_id": request.model},
        )

    capabilities = {str(c).lower().strip() for c in (descriptor.capabilities or [])}
    if "text_to_image" not in capabilities:
        raise_api_error(
            status_code=400,
            code="image_generation_capability_missing",
            message=f"Model {request.model} does not declare capability text_to_image",
            details={"model_id": request.model},
        )

    return descriptor


def _build_runtime_request(
    request: ImageGenerateRequest,
    *,
    progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> RuntimeImageGenerationRequest:
    return RuntimeImageGenerationRequest(
        prompt=request.prompt,
        negative_prompt=request.negative_prompt,
        width=request.width,
        height=request.height,
        num_inference_steps=request.num_inference_steps,
        guidance_scale=request.guidance_scale,
        seed=request.seed,
        image_format=request.image_format,
        progress_callback=progress_callback,
    )


async def _patch_generation_progress(
    *,
    job_id: Optional[str],
    current_step: int,
    total_steps: int,
) -> None:
    if not job_id:
        return
    progress = round((current_step / total_steps) * 100, 2) if total_steps > 0 else None
    await _patch_job(
        job_id,
        current_step=current_step,
        total_steps=total_steps,
        progress=progress,
        phase="generating",
    )


async def _generate_with_oom_retry(
    *,
    runtime: Any,
    factory: Any,
    descriptor: ModelDescriptor,
    request: ImageGenerateRequest,
    job_id: Optional[str],
    progress_callback: Callable[[int, int], Awaitable[None]],
) -> ImageGenerationResponse:
    try:
        if not await runtime.is_loaded():
            logger.info("[ImageGenerateAPI] runtime_load_start model=%s job_id=%s", descriptor.id, job_id or "-")
            await runtime.load()
            logger.info("[ImageGenerateAPI] runtime_load_done model=%s job_id=%s", descriptor.id, job_id or "-")

        if job_id:
            await _patch_job(job_id, phase="generating")
        response = await runtime.generate(_build_runtime_request(request, progress_callback=progress_callback))
        return cast(ImageGenerationResponse, response)
    except Exception as exc:
        if not _is_mps_oom_error(exc):
            raise
        logger.warning(
            "[ImageGenerateAPI] mps_oom_retry model=%s job_id=%s err=%s",
            descriptor.id,
            job_id or "-",
            exc,
        )
        await factory.unload_image_generation_runtime(descriptor.id)
        await _force_release_other_image_generation_runtimes(
            factory,
            reason="mps_oom_retry",
        )
        runtime = factory.create_image_generation_runtime(descriptor)
        if job_id:
            await _patch_job(job_id, phase="loading_runtime")
        logger.info("[ImageGenerateAPI] runtime_load_retry_start model=%s job_id=%s", descriptor.id, job_id or "-")
        await runtime.load()
        logger.info("[ImageGenerateAPI] runtime_load_retry_done model=%s job_id=%s", descriptor.id, job_id or "-")
        if job_id:
            await _patch_job(job_id, phase="generating")
        response = await runtime.generate(_build_runtime_request(request, progress_callback=progress_callback))
        return cast(ImageGenerationResponse, response)


async def _run_generation(
    request: ImageGenerateRequest,
    descriptor: ModelDescriptor,
    *,
    job_id: Optional[str] = None,
    tenant_id: str = "default",
) -> ImageGenerationResponse:
    tid = (str(tenant_id).strip() or "default")
    factory = get_runtime_factory()
    queue = get_inference_queue_manager().get_queue(descriptor.id, descriptor.runtime)

    if job_id:
        await _patch_job(job_id, status=ImageGenerationJobStatus.QUEUED, phase="queued")
        await _recompute_queue_positions(descriptor.id, tid)

    await factory.auto_release_unused_local_runtimes(
        keep_model_ids={descriptor.id},
        reason="image_generate_api",
    )

    logger.info(
        "[ImageGenerateAPI] request_start model=%s job_id=%s width=%s height=%s steps=%s guidance=%s seed=%s",
        descriptor.id,
        job_id or "-",
        request.width,
        request.height,
        request.num_inference_steps,
        request.guidance_scale,
        request.seed,
    )

    async def _run_under_queue() -> ImageGenerationResponse:
        # Image generation models have much larger unified-memory footprints than
        # chat runtimes. Before switching to a different image model, proactively
        # unload other cached image-generation runtimes to avoid MPS OOM on load.
        await _force_release_other_image_generation_runtimes(
            factory,
            keep_model_id=descriptor.id,
            reason="before_image_runtime_load",
        )
        runtime = factory.create_image_generation_runtime(descriptor)
        async with factory.model_usage(descriptor.id):
            async def _progress_callback(current_step: int, total_steps: int) -> None:
                await _patch_generation_progress(
                    job_id=job_id,
                    current_step=current_step,
                    total_steps=total_steps,
                )

            if job_id:
                await _patch_job(
                    job_id,
                    status=ImageGenerationJobStatus.RUNNING,
                    phase="preparing_runtime",
                    started_at=_utcnow(),
                    queue_position=None,
                )
                await _recompute_queue_positions(descriptor.id, tid)
            if job_id:
                await _patch_job(job_id, phase="loading_runtime")
            response = await _generate_with_oom_retry(
                runtime=runtime,
                factory=factory,
                descriptor=descriptor,
                request=request,
                job_id=job_id,
                progress_callback=_progress_callback,
            )

            response = _persist_image_result(response, job_id)
            logger.info(
                "[ImageGenerateAPI] request_done model=%s job_id=%s latency_ms=%s output=%sx%s",
                descriptor.id,
                job_id or "-",
                response.latency_ms,
                response.width,
                response.height,
            )
            return response

    response = await queue.run(_run_under_queue())
    return cast(ImageGenerationResponse, response)


async def _run_generation_job(job_id: str) -> None:
    job = await _get_job(job_id)
    if not job:
        return

    descriptor = _validate_descriptor(job.request)
    try:
        if job.cancelled:
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                error=JOB_CANCELLED_BEFORE_START_MSG,
            )
            return
        response = await _run_generation(
            job.request, descriptor, job_id=job_id, tenant_id=job.tenant_id
        )
        job = await _get_job(job_id)
        if job and job.cancelled:
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                result=response,
                error=JOB_CANCELLED_MSG,
            )
            return
        current_job = await _get_job(job_id)
        if current_job is None:
            return
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.SUCCEEDED,
            phase="completed",
            finished_at=_utcnow(),
            current_step=current_job.request.num_inference_steps,
            total_steps=current_job.request.num_inference_steps,
            progress=100.0,
            result=response,
        )
    except asyncio.CancelledError:
        logger.info("[ImageGenerateAPI] job_cancelled job_id=%s", job_id)
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.CANCELLED,
            phase="cancelled",
            finished_at=_utcnow(),
            error=JOB_CANCELLED_MSG,
        )
        raise
    except APIException as e:
        err_text = e.message
        logger.warning(
            "[ImageGenerateAPI] job_failed job_id=%s status=%s detail=%s",
            job_id,
            e.status_code,
            e.message,
        )
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.FAILED,
            phase="failed",
            finished_at=_utcnow(),
            error=err_text,
        )
    except Exception as e:
        current = await _get_job(job_id)
        if current and current.cancelled:
            logger.info("[ImageGenerateAPI] job_cancelled_after_runtime_signal job_id=%s", job_id)
            await _patch_job(
                job_id,
                status=ImageGenerationJobStatus.CANCELLED,
                phase="cancelled",
                finished_at=_utcnow(),
                error=JOB_CANCELLED_MSG,
            )
            return
        logger.exception("[ImageGenerateAPI] job_failed job_id=%s", job_id)
        await _patch_job(
            job_id,
            status=ImageGenerationJobStatus.FAILED,
            phase="failed",
            finished_at=_utcnow(),
            error=str(e),
        )
    finally:
        j2 = await _get_job(job_id)
        ftid = (str(j2.tenant_id).strip() or "default") if j2 else "default"
        await _recompute_queue_positions(descriptor.id, ftid)


@router.post(
    "/api/v1/images/generate",
    response_model=ImageGenerationResponse | ImageGenerationJobResponse,
)
async def generate_image(
    payload: ImageGenerateRequest,
    wait: Annotated[bool, Query(description="true=同步等待结果；false=创建异步任务并返回 job")] = True,
    *,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationResponse | ImageGenerationJobResponse:
    descriptor = _validate_descriptor(payload)
    tid = resolve_api_tenant_id(http_request)

    if wait:
        token = _image_store_bind.set(db.get_bind())
        try:
            try:
                return await _run_generation(payload, descriptor, tenant_id=tid)
            except APIException:
                raise
            except Exception as e:
                logger.exception("Image generation failed for model=%s", descriptor.id)
                raise_api_error(
                    status_code=500,
                    code="image_generation_failed",
                    message=str(e),
                    details={"model_id": descriptor.id},
                )
        finally:
            _image_store_bind.reset(token)

    pending_limit = max(1, int(getattr(settings, "image_generation_max_pending_jobs_per_model", 4)))
    pending_count = await _get_pending_count_for_model(descriptor.id, tenant_id=tid)
    if pending_count >= pending_limit:
        raise_api_error(
            status_code=429,
            code="image_generation_queue_full",
            message=(
                f"IMAGE_GENERATION_QUEUE_FULL: model={descriptor.id} "
                f"pending={pending_count} limit={pending_limit}"
            ),
            details={
                "model_id": descriptor.id,
                "pending_count": pending_count,
                "limit": pending_limit,
            },
        )

    job_id = str(uuid4())
    queued_count = await _get_queued_count_for_model(descriptor.id, tenant_id=tid)
    job = _ImageGenerationJob(
        job_id=job_id,
        request=_clone_request(payload),
        status=ImageGenerationJobStatus.QUEUED,
        created_at=_utcnow(),
        tenant_id=tid,
        phase="queued",
        queue_position=queued_count + 1,
    )
    token = _image_store_bind.set(db.get_bind())
    try:
        await _save_job(job)
        task = asyncio.create_task(_run_generation_job(job_id))
        await _patch_job(job_id, task=task)
        logger.info("[ImageGenerateAPI] job_created job_id=%s model=%s", job_id, descriptor.id)
        saved = await _get_job(job_id)
        if saved is None:
            raise_api_error(
                status_code=500,
                code="image_generation_job_state_missing",
                message=f"Image generation job state missing: {job_id}",
                details={"job_id": job_id},
            )
            raise AssertionError("unreachable")
        return _job_to_response(saved)
    finally:
        _image_store_bind.reset(token)


@router.get("/api/v1/images/jobs/{job_id}", response_model=ImageGenerationJobResponse)
async def get_image_generation_job(
    job_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationJobResponse:
    tid = resolve_api_tenant_id(http_request)
    job = await _get_job(job_id)
    if job:
        if (str(job.tenant_id).strip() or "default") != tid:
            raise_api_error(
                status_code=404,
                code="image_generation_job_not_found",
                message=f"Image generation job not found: {job_id}",
                details={"job_id": job_id},
            )
        return _job_to_response(job, include_base64=False)
    row = db.get(ImageGenerationJobORM, job_id)
    if not row:
        raise_api_error(
            status_code=404,
            code="image_generation_job_not_found",
            message=f"Image generation job not found: {job_id}",
            details={"job_id": job_id},
        )
    row_tid = (str(getattr(row, "tenant_id", None) or "").strip() or "default")
    if row_tid != tid:
        raise_api_error(
            status_code=404,
            code="image_generation_job_not_found",
            message=f"Image generation job not found: {job_id}",
            details={"job_id": job_id},
        )
    return _orm_to_job_response(row, include_base64=False)


@router.get("/api/v1/images/jobs", response_model=ImageGenerationJobListResponse)
async def list_image_generation_jobs(
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(description="search prompt")] = None,
    sort: Annotated[str, Query(description="created_at_desc|created_at_asc")] = "created_at_desc",
    include_result: Annotated[bool, Query()] = False,
) -> ImageGenerationJobListResponse:
    normalized_status = (status or "").strip().lower()
    normalized_model = (model or "").strip()
    normalized_q = (q or "").strip()
    normalized_sort = (sort or "created_at_desc").strip().lower()
    tid = resolve_api_tenant_id(http_request)
    query = db.query(ImageGenerationJobORM).filter(ImageGenerationJobORM.tenant_id == tid)
    if normalized_status:
        query = query.filter(ImageGenerationJobORM.status == normalized_status)
    if normalized_model:
        query = query.filter(ImageGenerationJobORM.model == normalized_model)
    if normalized_q:
        query = query.filter(ImageGenerationJobORM.prompt.ilike(f"%{normalized_q}%"))
    if normalized_sort == "created_at_asc":
        order_by = ImageGenerationJobORM.created_at.asc()
    else:
        order_by = ImageGenerationJobORM.created_at.desc()
    total = query.count()
    rows = query.order_by(order_by).offset(offset).limit(limit).all()
    items = [_row_to_response(row, include_result=include_result, include_base64=False) for row in rows]
    return ImageGenerationJobListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_next=(offset + len(items)) < total,
    )


@router.delete("/api/v1/images/jobs/{job_id}", response_model=ImageGenerationJobDeleteResponse)
async def delete_image_generation_job(
    job_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationJobDeleteResponse:
    tid = resolve_api_tenant_id(http_request)
    row = db.get(ImageGenerationJobORM, job_id)
    async with _IMAGE_JOBS_LOCK:
        job = _IMAGE_JOBS.get(job_id)
        if job and (str(job.tenant_id).strip() or "default") != tid:
            job = None
        model_id = job.request.model if job else None
        if job and job.status in {ImageGenerationJobStatus.QUEUED, ImageGenerationJobStatus.RUNNING}:
            _raise_job_delete_conflict(job_id)
        removed = _IMAGE_JOBS.pop(job_id, None) if job else None

    if removed is None and row is None:
        _raise_job_not_found(job_id)
    if row is not None:
        row_tid = (str(getattr(row, "tenant_id", None) or "").strip() or "default")
        if row_tid != tid:
            _raise_job_not_found(job_id)
    if model_id is None and row is not None:
        model_id = cast(str, row.model)
    if row is not None and _is_running_job_status(cast(str, row.status)):
        _raise_job_delete_conflict(job_id)

    output_path, thumbnail_path = _extract_result_paths(removed, row)
    _cleanup_generated_files(
        job_id=job_id,
        output_path=output_path,
        thumbnail_path=thumbnail_path,
    )

    token = _image_store_bind.set(db.get_bind())
    try:
        await asyncio.to_thread(_db_delete_job, job_id)
        if model_id:
            await _recompute_queue_positions(model_id, tid)
    finally:
        _image_store_bind.reset(token)
    logger.info("[ImageGenerateAPI] job_deleted job_id=%s", job_id)
    return ImageGenerationJobDeleteResponse(ok=True, job_id=job_id)


@router.post("/api/v1/images/jobs/{job_id}/cancel", response_model=ImageGenerationJobResponse)
async def cancel_image_generation_job(
    job_id: str,
    http_request: Request,
    *,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationJobResponse:
    tid = resolve_api_tenant_id(http_request)
    job = await _get_job(job_id)
    if not job:
        raise_api_error(
            status_code=404,
            code="image_generation_job_not_found",
            message=f"Image generation job not found: {job_id}",
            details={"job_id": job_id},
        )
        raise AssertionError("unreachable")
    assert job is not None
    if (str(job.tenant_id).strip() or "default") != tid:
        raise_api_error(
            status_code=404,
            code="image_generation_job_not_found",
            message=f"Image generation job not found: {job_id}",
            details={"job_id": job_id},
        )
        raise AssertionError("unreachable")
    if job.status in {ImageGenerationJobStatus.SUCCEEDED, ImageGenerationJobStatus.FAILED, ImageGenerationJobStatus.CANCELLED}:
        return _job_to_response(job)

    descriptor = _validate_descriptor(job.request)
    runtime = get_runtime_factory().create_image_generation_runtime(descriptor)
    cancelled_runtime = False
    cancel_fn = getattr(runtime, "cancel", None)
    if callable(cancel_fn):
        cancelled_runtime = bool(await cancel_fn())

    token = _image_store_bind.set(db.get_bind())
    try:
        await _patch_job(job_id, cancelled=True, phase="cancel_requested")
        if job.status == ImageGenerationJobStatus.QUEUED and job.task and not job.task.done():
            job.task.cancel()
            await _recompute_queue_positions(descriptor.id, tid)

        logger.info(
            "[ImageGenerateAPI] job_cancel_requested job_id=%s model=%s runtime_cancelled=%s",
            job_id,
            descriptor.id,
            cancelled_runtime,
        )
        saved = await _get_job(job_id)
        if saved is None:
            raise_api_error(
                status_code=500,
                code="image_generation_job_state_missing",
                message=f"Image generation job state missing: {job_id}",
                details={"job_id": job_id},
            )
            raise AssertionError("unreachable")
        return _job_to_response(saved)
    finally:
        _image_store_bind.reset(token)


@router.get("/api/v1/images/jobs/{job_id}/file")
async def download_image_generation_job_file(
    job_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    await _require_image_job_tenant(job_id, resolve_api_tenant_id(http_request), db)
    job = await _get_job(job_id)
    output_path_str = job.result.output_path if job and job.result else None
    mime_type = job.result.mime_type if job and job.result else None
    if not output_path_str:
        row = db.get(ImageGenerationJobORM, job_id)
        if not row or not row.result_json:
            raise_api_error(
                status_code=404,
                code="image_generation_output_not_found",
                message=f"Generated image file not found for job: {job_id}",
                details={"job_id": job_id},
            )
        result_json = cast(Dict[str, Any], row.result_json)
        output_path_str = cast(Optional[str], result_json.get("output_path"))
        mime_type = cast(Optional[str], result_json.get("mime_type")) or mime_type
    if not output_path_str:
        raise_api_error(
            status_code=404,
            code="image_generation_output_not_found",
            message=f"Generated image file not found for job: {job_id}",
            details={"job_id": job_id},
        )
    assert output_path_str is not None

    output_path = Path(output_path_str).resolve()
    if not output_path.is_file():
        raise_api_error(
            status_code=404,
            code="image_generation_output_not_found",
            message=f"Generated image file not found: {output_path}",
            details={"job_id": job_id, "path": str(output_path)},
        )

    return FileResponse(str(output_path), media_type=mime_type or DEFAULT_IMAGE_MIME, filename=output_path.name)


@router.get("/api/v1/images/jobs/{job_id}/thumbnail")
async def download_image_generation_job_thumbnail(
    job_id: str,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    await _require_image_job_tenant(job_id, resolve_api_tenant_id(http_request), db)
    job = await _get_job(job_id)
    thumb_path = job.result.thumbnail_path if job and job.result else None
    mime_type = job.result.mime_type if job and job.result else None
    if not thumb_path and job and job.result:
        payload = job.result.model_dump(mode="json")
        thumb_path = _ensure_thumbnail_for_payload(job_id, payload)
        if thumb_path:
            updated_result = ImageGenerationResponse.model_validate(payload)
            token_th = _image_store_bind.set(db.get_bind())
            try:
                await _patch_job(job_id, result=updated_result)
            finally:
                _image_store_bind.reset(token_th)
            mime_type = updated_result.mime_type or mime_type
    if not thumb_path:
        thumb_path, mime_type = _load_thumbnail_from_db(
            job_id=job_id,
            current_mime_type=mime_type,
            db=db,
        )
    if not thumb_path:
        _raise_thumbnail_not_found(job_id)

    assert thumb_path is not None
    path = Path(thumb_path).resolve()
    if not path.is_file():
        raise_api_error(
            status_code=404,
            code="image_generation_thumbnail_not_found",
            message=f"Generated thumbnail file not found: {path}",
            details={"job_id": job_id, "path": str(path)},
        )
    return FileResponse(str(path), media_type=mime_type or DEFAULT_IMAGE_MIME, filename=path.name)


@router.get("/api/v1/images/warmup/latest", response_model=ImageGenerationWarmupResponse)
async def get_latest_image_generation_warmup(
    http_request: Request,
    model: Annotated[str | None, Query()] = None,
    *,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationWarmupResponse:
    tid = resolve_api_tenant_id(http_request)
    token = _image_store_bind.set(db.get_bind())
    try:
        row = await asyncio.to_thread(
            _db_get_latest_warmup, model.strip() if model else None, tenant_id=tid
        )
        if row is None:
            raise_api_error(
                status_code=404,
                code="image_generation_warmup_not_found",
                message="No warmup record found",
                details={"model": model},
            )
        assert row is not None
        return _orm_to_warmup_response(row)
    finally:
        _image_store_bind.reset(token)


@router.post("/api/v1/images/warmup", response_model=ImageGenerationWarmupCompletedResponse)
async def warmup_image_generation_runtime(
    body: ImageWarmupRequest,
    http_request: Request,
    *,
    db: Annotated[Session, Depends(get_db)],
) -> ImageGenerationWarmupCompletedResponse:
    tid = resolve_api_tenant_id(http_request)
    image_request = ImageGenerateRequest(
        model=body.model,
        prompt=body.prompt,
        width=body.width,
        height=body.height,
        num_inference_steps=body.num_inference_steps,
        guidance_scale=body.guidance_scale,
        seed=body.seed,
        image_format="PNG",
    )
    descriptor = _validate_descriptor(image_request)
    started_at = time_started = _utcnow()
    warmup_id = str(uuid4())
    token = _image_store_bind.set(db.get_bind())
    try:
        try:
            response = await _run_generation(image_request, descriptor, job_id=None, tenant_id=tid)
            elapsed_ms = int((_utcnow() - time_started).total_seconds() * 1000)
            finished_at = _utcnow()
            await asyncio.to_thread(
                _db_create_warmup,
                warmup_id=warmup_id,
                model=descriptor.id,
                prompt=body.prompt,
                request_json=body.model_dump(mode="json"),
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ms=elapsed_ms,
                output_path=response.output_path,
                width=response.width,
                height=response.height,
                result_json=response.model_dump(mode="json"),
                tenant_id=tid,
            )
        except Exception as e:
            finished_at = _utcnow()
            elapsed_ms = int((finished_at - time_started).total_seconds() * 1000)
            await asyncio.to_thread(
                _db_create_warmup,
                warmup_id=warmup_id,
                model=descriptor.id,
                prompt=body.prompt,
                request_json=body.model_dump(mode="json"),
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ms=elapsed_ms,
                output_path=None,
                width=body.width,
                height=body.height,
                result_json=None,
                status="failed",
                error=str(e),
                tenant_id=tid,
            )
            raise
        logger.info(
            "[ImageGenerateAPI] warmup_done model=%s elapsed_ms=%s output=%sx%s",
            descriptor.id,
            elapsed_ms,
            response.width,
            response.height,
        )
        return ImageGenerationWarmupCompletedResponse(
            ok=True,
            warmup_id=warmup_id,
            model=descriptor.id,
            started_at=started_at,
            elapsed_ms=elapsed_ms,
            output_path=response.output_path,
            width=response.width,
            height=response.height,
        )
    finally:
        _image_store_bind.reset(token)
