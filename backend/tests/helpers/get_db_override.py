"""FastAPI 集成测试：与 Depends(get_db) / 审计中间件对齐的 dependency override。"""

from __future__ import annotations

from collections.abc import Callable, Generator

from sqlalchemy.orm import Session
from starlette.requests import Request

from core.data.base import DB_ENGINE_STATE_KEY


def session_factory_as_get_db_override(
    session_factory: Callable[[], Session],
) -> Callable[..., Generator[Session, None, None]]:
    """返回可供 ``dependency_overrides[get_db]`` 使用的生成器，并写入 ``DB_ENGINE_STATE_KEY``。"""

    def _override(request: Request) -> Generator[Session, None, None]:
        db = session_factory()
        setattr(request.state, DB_ENGINE_STATE_KEY, db.get_bind())
        try:
            yield db
        finally:
            db.close()

    return _override
