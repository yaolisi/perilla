"""图片 API：get_db override 下的落库与读库路径集成（异步生成含 stub；另覆盖 ORM 回退与 warmup/latest）。"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import asynccontextmanager
from core.data.base import Base
from core.data.models.image_generation import ImageGenerationJobORM, ImageGenerationWarmupORM
from core.models.descriptor import ModelDescriptor
from core.runtimes.image_generation_types import ImageGenerationResponse
from tests.helpers import build_router_integration_test_client


_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _stub_descriptor() -> ModelDescriptor:
    return ModelDescriptor(
        id="img_stub_ig",
        name="Stub Image Gen",
        model_type="image_generation",
        provider="stub",
        provider_model_id="img_stub_ig",
        runtime="stub_ig_rt",
        capabilities=["text_to_image"],
    )


class _StubRegistry:
    def __init__(self, desc: ModelDescriptor) -> None:
        self._desc = desc

    def get_model(self, model_id: str):
        if model_id == self._desc.id:
            return self._desc
        return None


class _InlineQueue:
    async def run(self, coro, priority: str = "medium", preemption_key: str | None = None):
        return await coro


class _StubQueueManager:
    def get_queue(self, model_id: str, runtime: str):
        return _InlineQueue()


class _StubImageRuntime:
    async def is_loaded(self) -> bool:
        return True

    async def load(self) -> None:
        return None

    async def generate(self, _request):
        return ImageGenerationResponse(
            model="img_stub_ig",
            mime_type="image/png",
            width=1,
            height=1,
            latency_ms=1,
            image_base64=_TINY_PNG_B64,
        )


class _StubRuntimeFactory:
    async def auto_release_unused_local_runtimes(self, **kwargs) -> None:
        return None

    @asynccontextmanager
    async def model_usage(self, _model_id: str):
        yield None

    def create_image_generation_runtime(self, _descriptor):
        return _StubImageRuntime()


@pytest.fixture()
def images_api_db_client(tmp_path):
    """仅 SQLite + get_db override，无推理 stub；用于读路径集成。"""
    db_file = tmp_path / "images_read.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    import api.images as images_api

    images_api._IMAGE_JOBS.clear()

    client = build_router_integration_test_client(session_factory, images_api)

    return client, session_factory


@pytest.fixture()
def images_integration_client(tmp_path, monkeypatch):
    db_file = tmp_path / "images_integration.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )

    import api.images as images_api

    images_api._IMAGE_JOBS.clear()

    desc = _stub_descriptor()
    monkeypatch.setattr(images_api, "get_model_registry", lambda: _StubRegistry(desc))
    monkeypatch.setattr(images_api, "get_inference_queue_manager", lambda: _StubQueueManager())
    monkeypatch.setattr(images_api, "get_runtime_factory", lambda: _StubRuntimeFactory())

    async def _noop_force(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(images_api, "_force_release_other_image_generation_runtimes", _noop_force)

    client = build_router_integration_test_client(session_factory, images_api)
    yield client, session_factory, images_api


def test_async_generate_persists_job_to_overridden_db(images_integration_client) -> None:
    client, session_factory, _ = images_integration_client

    resp = client.post(
        "/api/v1/images/generate?wait=false",
        json={"model": "img_stub_ig", "prompt": "integration probe"},
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json().get("job_id")
    assert isinstance(job_id, str) and len(job_id) > 0

    row = None
    for _ in range(80):
        time.sleep(0.02)
        with session_factory() as db:
            row = db.get(ImageGenerationJobORM, job_id)
            if row is not None:
                break
    assert row is not None, "job row should be persisted via _image_store_bind + get_db override"
    assert row.model == "img_stub_ig"


def test_get_job_reads_db_when_not_in_memory(images_api_db_client) -> None:
    client, session_factory = images_api_db_client
    jid = "job_orm_fallback_1"
    with session_factory() as db:
        db.add(
            ImageGenerationJobORM(
                job_id=jid,
                model="img_stub_ig",
                prompt="probe",
                status="succeeded",
                phase="completed",
                request_json={
                    "model": "img_stub_ig",
                    "prompt": "probe",
                    "image_format": "PNG",
                },
                result_json={
                    "model": "img_stub_ig",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "image_base64": _TINY_PNG_B64,
                },
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    resp = client.get(f"/api/v1/images/jobs/{jid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("job_id") == jid
    assert body.get("model") == "img_stub_ig"


def test_warmup_latest_reads_overridden_db(images_api_db_client) -> None:
    client, session_factory = images_api_db_client
    with session_factory() as db:
        db.add(
            ImageGenerationWarmupORM(
                warmup_id="wu_db_1",
                model="warm_m1",
                prompt="warm",
                status="succeeded",
                elapsed_ms=12,
                output_path=None,
                width=64,
                height=64,
                error=None,
                request_json={},
                result_json={},
                latest=True,
                created_at=datetime.now(UTC),
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        db.commit()

    resp = client.get("/api/v1/images/warmup/latest", params={"model": "warm_m1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("warmup_id") == "wu_db_1"
    assert body.get("model") == "warm_m1"


def test_sync_generate_wait_true_returns_payload(images_integration_client) -> None:
    """wait=true：_image_store_bind 覆盖 _run_generation 全链路，stub 不跑真实推理。"""
    client, _, _ = images_integration_client
    resp = client.post(
        "/api/v1/images/generate?wait=true",
        json={"model": "img_stub_ig", "prompt": "sync probe"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("model") == "img_stub_ig"
    assert isinstance(body.get("image_base64"), str) and len(body["image_base64"]) > 10


def test_list_image_jobs_reads_from_overridden_db(images_api_db_client) -> None:
    client, session_factory = images_api_db_client
    now = datetime.now(UTC)
    with session_factory() as db:
        for jid in ("list_j1", "list_j2"):
            db.add(
                ImageGenerationJobORM(
                    job_id=jid,
                    model="m_list",
                    prompt="p",
                    status="succeeded",
                    phase="completed",
                    request_json={"model": "m_list", "prompt": "p", "image_format": "PNG"},
                    result_json={
                        "model": "m_list",
                        "mime_type": "image/png",
                        "width": 1,
                        "height": 1,
                        "image_base64": _TINY_PNG_B64,
                    },
                    created_at=now,
                )
            )
        db.commit()

    resp = client.get("/api/v1/images/jobs", params={"limit": 50, "model": "m_list"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("total") == 2
    ids = {item["job_id"] for item in data.get("items", [])}
    assert ids == {"list_j1", "list_j2"}


def test_delete_job_removes_orm_row_from_overridden_db(images_api_db_client) -> None:
    """DELETE 走 to_thread(_db_delete_job)，须与 Depends(get_db) 同引擎。"""
    client, session_factory = images_api_db_client
    jid = "job_delete_probe"
    with session_factory() as db:
        db.add(
            ImageGenerationJobORM(
                job_id=jid,
                model="m_del",
                prompt="p",
                status="succeeded",
                phase="completed",
                request_json={"model": "m_del", "prompt": "p", "image_format": "PNG"},
                result_json={
                    "model": "m_del",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "image_base64": _TINY_PNG_B64,
                },
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    resp = client.delete(f"/api/v1/images/jobs/{jid}")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("ok") is True

    with session_factory() as db:
        assert db.get(ImageGenerationJobORM, jid) is None


def test_cancel_endpoint_ok_with_stub_job(images_integration_client) -> None:
    """取消路径对 _patch_job / _recompute 设置 _image_store_bind（快速任务可能已终态，仍应 200）。"""
    client, _, _ = images_integration_client
    r = client.post(
        "/api/v1/images/generate?wait=false",
        json={"model": "img_stub_ig", "prompt": "cancel probe"},
    )
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    c = client.post(f"/api/v1/images/jobs/{jid}/cancel")
    assert c.status_code == 200, c.text
    body = c.json()
    assert body.get("job_id") == jid
