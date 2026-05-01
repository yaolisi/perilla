"""图片 API：_image_store_bind 与 _open_image_db_session 行为（与 get_db 测试 override 对齐）。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api.images as images_api
from api.images import ImageGenerateRequest, _ImageGenerationJob, _db_upsert_job
from core.data.base import Base
from core.data.models.image_generation import ImageGenerationJobORM
from core.runtimes.image_generation_types import ImageGenerationJobStatus


def test_open_image_db_session_prefers_context_bind(tmp_path) -> None:
    db_file = tmp_path / "bind_probe.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    token = images_api._image_store_bind.set(engine)
    try:
        sess = images_api._open_image_db_session()
        try:
            assert sess.get_bind() is engine
        finally:
            sess.close()
    finally:
        images_api._image_store_bind.reset(token)


def test_db_upsert_prefers_context_bind_over_get_engine(tmp_path, monkeypatch) -> None:
    """落库辅助函数在设置了上下文 bind 时写入该引擎，而非全局 get_engine()。"""
    db_a = tmp_path / "context_a.db"
    db_b = tmp_path / "global_b.db"
    engine_a = create_engine(f"sqlite:///{db_a}", connect_args={"check_same_thread": False})
    engine_b = create_engine(f"sqlite:///{db_b}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine_a)
    Base.metadata.create_all(bind=engine_b)

    monkeypatch.setattr(images_api, "get_engine", lambda: engine_b)

    job = _ImageGenerationJob(
        job_id="bind-upsert-probe",
        request=ImageGenerateRequest(model="m", prompt="p"),
        status=ImageGenerationJobStatus.QUEUED,
        created_at=datetime.now(UTC),
    )
    token = images_api._image_store_bind.set(engine_a)
    try:
        _db_upsert_job(job)
    finally:
        images_api._image_store_bind.reset(token)

    Sa = sessionmaker(bind=engine_a, autocommit=False, autoflush=False, expire_on_commit=False)
    Sb = sessionmaker(bind=engine_b, autocommit=False, autoflush=False, expire_on_commit=False)
    with Sa() as sa:
        assert sa.get(ImageGenerationJobORM, "bind-upsert-probe") is not None
    with Sb() as sb:
        assert sb.get(ImageGenerationJobORM, "bind-upsert-probe") is None
