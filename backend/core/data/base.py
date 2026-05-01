"""
数据库连接与 Session 管理
优化并发控制：
1. WAL 模式支持更好的并发读写（SQLite）
2. busy_timeout / 连接池与超时
3. 线程安全配置
"""
from pathlib import Path
from typing import Any, Generator, Iterator, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.exc import OperationalError
from starlette.requests import HTTPConnection

from config.settings import settings
from log import logger

# 与 middleware/audit_log 等约定：请求级 Session 的 bind，用于响应后写库与 Depends(get_db) 对齐（含测试 override）
DB_ENGINE_STATE_KEY = "sqlalchemy_engine"

Base = declarative_base()
metadata = MetaData()


def get_db_path() -> Path:
    """获取数据库路径"""
    if settings.db_path:
        return Path(settings.db_path)
    root = Path(__file__).resolve().parents[3]
    return root / "backend" / "data" / "platform.db"


def get_database_url() -> str:
    """获取数据库 URL：优先使用 database_url（可切 PostgreSQL），否则回落 SQLite 文件。"""
    raw = (getattr(settings, "database_url", "") or "").strip()
    if raw:
        return raw
    db_path = get_db_path()
    return f"sqlite:///{db_path}"


def _is_sqlite_url(db_url: str) -> bool:
    return db_url.startswith("sqlite:")


def is_sqlite_url(db_url: str) -> bool:
    """公开判断：当前解析后的 JDBC 风格 URL 是否为 SQLite。"""
    return _is_sqlite_url(db_url)


def _ensure_common_indexes(engine: Engine) -> None:
    """为高频查询补齐索引（兼容存量库）。"""
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_created ON agent_sessions (user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow_created ON workflow_executions (workflow_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_executions_state_created ON workflow_executions (state, created_at)",
    ]
    try:
        with engine.connect() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.commit()
    except Exception as e:
        logger.warning(f"[Data] Failed to ensure common indexes: {e}")


def create_engine_instance() -> Engine:
    """创建数据库引擎（优化并发配置）"""
    db_url = get_database_url()
    connect_args: dict = {}
    if _is_sqlite_url(db_url):
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {
            "check_same_thread": False,  # 允许多线程访问
            "timeout": 30.0,  # 锁等待超时（秒）
        }
    else:
        from core.data.pg_connect_args import merge_postgresql_connect_args

        connect_args.update(merge_postgresql_connect_args(db_url, sync_psycopg=True))

    pool_timeout = float(
        max(1.0, min(600.0, float(getattr(settings, "db_pool_timeout_seconds", 30.0))))
    )
    engine_kw: dict[str, Any] = {
        "connect_args": connect_args,
        "echo": False,
        "pool_pre_ping": True,  # 连接前健康检查
        "pool_recycle": max(60, int(getattr(settings, "db_pool_recycle_seconds", 1800))),
        "max_overflow": max(0, int(getattr(settings, "db_max_overflow", 20))),
        "pool_size": max(1, int(getattr(settings, "db_pool_size", 10))),
    }
    if not _is_sqlite_url(db_url):
        engine_kw["pool_timeout"] = pool_timeout
    engine = create_engine(db_url, **engine_kw)

    if _is_sqlite_url(db_url):
        # 启用 WAL 模式以提升并发性能
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA synchronous=NORMAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))  # 30 秒忙等待
                conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB 缓存
                conn.commit()
            logger.info("[Data] SQLite concurrency optimizations enabled (WAL mode)")
        except Exception as e:
            logger.warning(f"[Data] Failed to enable WAL mode: {e}")

    _ensure_common_indexes(engine)
    return engine


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """懒加载引擎：避免 import core.data.base 时立即建连（数据库暂不可用时仍可导入其它模块）。"""
    global _engine
    if _engine is None:
        _engine = create_engine_instance()
    return _engine


def dispose_engine() -> None:
    """关闭连接池（进程退出 / 优雅关停时调用）；下次 get_engine() 会重建引擎。"""
    global _engine
    if _engine is None:
        return
    eng = _engine
    _engine = None
    try:
        SessionLocal._maker = None  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        eng.dispose()
        logger.info("[Data] SQLAlchemy engine disposed (connection pool closed)")
    except Exception as e:
        logger.warning("[Data] SQLAlchemy engine dispose failed: %s", e)


def sessionmaker_for_engine(engine: Engine) -> sessionmaker:
    """与 SessionLocal 相同选项；后台任务 / SSE 等可从现有 Session 的 engine（含测试 override）开新连接。"""
    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


class _SessionLocalFactory:
    """与历史 sessionmaker 用法兼容：SessionLocal() 返回 Session。"""

    _maker: Optional[sessionmaker] = None

    def __call__(self, **kwargs: Any) -> Session:
        if self._maker is None:
            self._maker = sessionmaker_for_engine(get_engine())
        return self._maker(**kwargs)


SessionLocal = _SessionLocalFactory()


def get_db(conn: HTTPConnection) -> Generator[Session, None, None]:
    """获取数据库会话（依赖注入）。用法：FastAPI Depends(get_db)"""
    db = SessionLocal()
    setattr(conn.state, DB_ENGINE_STATE_KEY, db.get_bind())
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session(retry_count: int = 3, retry_delay: float = 0.1) -> Iterator[Session]:
    """
    获取数据库会话（非 FastAPI）。

    Args:
        retry_count / retry_delay: 保留兼容；contextmanager 只能 yield 一次，无法在失败时自动重跑整段业务。
        锁竞争依赖 SQLite busy_timeout/WAL；失败时抛出 OperationalError。

    Usage:
        with db_session() as db:
            ...
    """
    _ = (retry_count, retry_delay)  # API 兼容占位
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except OperationalError as e:
        logger.error(f"[Data] Database operational error: {e}")
        db.rollback()
        raise
    except Exception as e:
        logger.error(f"[Data] Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """初始化数据库（创建所有已注册的 ORM 表）"""
    Base.metadata.create_all(bind=get_engine())
    logger.info("[Data] Database tables created")
