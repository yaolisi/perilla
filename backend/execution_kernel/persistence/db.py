"""
Database Configuration
SQLAlchemy 2.0 异步引擎配置

注意：系统集成使用统一的 platform.db，所有表在同一数据库中管理。
"""

from pathlib import Path
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import Engine, create_engine, text
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Dict, Generator, Optional
import os
import logging

from execution_kernel.models.graph_instance import Base

# V2.6: 显式 import 以注册 ExecutionEventDB 到 Base.metadata
# 这样 create_tables() 会创建 execution_event 表
import execution_kernel.events.event_store  # noqa: F401


logger = logging.getLogger("ai_platform")


def get_platform_db_path() -> Path:
    """
    获取统一的 platform.db 路径
    
    优先级：
    1. settings.db_path (如果配置)
    2. 默认 backend/data/platform.db
    """
    try:
        from config.settings import settings
        if settings.db_path:
            return Path(settings.db_path)
    except Exception:
        pass
    
    # 默认路径：backend/data/platform.db
    root = Path(__file__).resolve().parents[3]
    data_dir = root / "backend" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "platform.db"


def get_default_database_url() -> str:
    """获取默认数据库 URL（使用统一的 platform.db）"""
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if db_url:
        # 复用主服务 DATABASE_URL；异步引擎优先 asyncpg
        return db_url.replace("+psycopg2", "+asyncpg")
    db_path = get_platform_db_path()
    return f"sqlite+aiosqlite:///{db_path}"


# 默认数据库 URL（使用统一的 platform.db）
DEFAULT_DATABASE_URL = get_default_database_url()
# 生产环境可切换到 PostgreSQL：
# DEFAULT_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/execution_kernel"


def _sqlalchemy_pool_kwargs(database_url: str) -> Dict[str, Any]:
    """
    SQLite（含 aiosqlite 内存 / 文件）使用 StaticPool/NullPool 等，不能传 pool_size、max_overflow。
    """
    base: Dict[str, Any] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        return base
    base["pool_recycle"] = max(60, int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")))
    base["max_overflow"] = max(0, int(os.getenv("DB_MAX_OVERFLOW", "20")))
    base["pool_size"] = max(1, int(os.getenv("DB_POOL_SIZE", "10")))
    return base


class Database:
    """数据库管理器"""
    
    def __init__(self, database_url: Optional[str] = None) -> None:
        db_url = database_url or os.getenv("EXECUTION_KERNEL_DB_URL") or DEFAULT_DATABASE_URL
        self.database_url: str = db_url
        self._async_engine: Optional[AsyncEngine] = None
        self._sync_engine: Optional[Engine] = None
        self._async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._sync_session_factory: Optional[sessionmaker[Session]] = None
    
    @property
    def async_engine(self) -> AsyncEngine:
        """异步引擎"""
        if self._async_engine is None:
            connect_args = {}
            if self.database_url.startswith("sqlite"):
                connect_args = {"timeout": 30}
            self._async_engine = create_async_engine(
                self.database_url,
                echo=False,
                future=True,
                connect_args=connect_args,
                **_sqlalchemy_pool_kwargs(self.database_url),
            )
            self._configure_sqlite_pragmas(self._async_engine.sync_engine)
        return self._async_engine
    
    @property
    def sync_engine(self) -> Engine:
        """同步引擎"""
        if self._sync_engine is None:
            # 转换为同步 URL
            sync_url = self.database_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg2")
            connect_args = {}
            if sync_url.startswith("sqlite"):
                connect_args = {"timeout": 30}
            self._sync_engine = create_engine(
                sync_url,
                echo=False,
                future=True,
                connect_args=connect_args,
                **_sqlalchemy_pool_kwargs(sync_url),
            )
            self._configure_sqlite_pragmas(self._sync_engine)
        return self._sync_engine

    @staticmethod
    def _configure_sqlite_pragmas(engine: Engine) -> None:
        """为 SQLite 连接设置并发友好的 PRAGMA。"""
        if not str(engine.url).startswith("sqlite"):
            return

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    
    def get_async_session_factory(self) -> async_sessionmaker:
        """获取异步 Session 工厂"""
        if self._async_session_factory is None:
            self._async_session_factory = async_sessionmaker(
                bind=self.async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._async_session_factory
    
    def get_sync_session_factory(self) -> sessionmaker[Session]:
        """获取同步 Session 工厂"""
        if self._sync_session_factory is None:
            self._sync_session_factory = sessionmaker(
                bind=self.sync_engine,
                expire_on_commit=False,
            )
        return self._sync_session_factory
    
    @asynccontextmanager
    async def async_session(self) -> AsyncGenerator[AsyncSession, None]:
        """异步 Session 上下文管理器"""
        session = self.get_async_session_factory()()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    @contextmanager
    def sync_session(self) -> Generator[Session, None, None]:
        """同步 Session 上下文管理器"""
        session = self.get_sync_session_factory()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    async def create_tables(self) -> None:
        """创建所有表"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await self._migrate_legacy_schema(conn)
    
    async def drop_tables(self) -> None:
        """删除所有表（仅用于测试）"""
        async with self.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    
    async def close(self) -> None:
        """关闭连接"""
        if self._async_engine:
            await self._async_engine.dispose()
        if self._sync_engine:
            self._sync_engine.dispose()

    async def _migrate_legacy_schema(self, conn: AsyncConnection) -> None:
        """
        兼容旧版 schema：
        - graph_definitions 缺少 graph_id 列时自动补齐并回填
        """
        try:
            result = await conn.execute(text("PRAGMA table_info(graph_definitions)"))
            cols = {str(row[1]) for row in result.fetchall()}
            if "graph_id" not in cols:
                await conn.execute(text("ALTER TABLE graph_definitions ADD COLUMN graph_id VARCHAR(64)"))
                await conn.execute(text("UPDATE graph_definitions SET graph_id = id WHERE graph_id IS NULL OR graph_id = ''"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_graph_definitions_graph_id ON graph_definitions (graph_id)"))
                logger.info("[ExecutionKernel] Migrated legacy graph_definitions table: added graph_id column")
        except Exception as e:
            logger.warning(f"[ExecutionKernel] Legacy schema migration skipped/failed: {e}")


# 全局数据库实例
_db: Optional[Database] = None


def get_database() -> Database:
    """获取全局数据库实例"""
    global _db
    if _db is None:
        _db = Database()
    return _db


def init_database(database_url: Optional[str] = None) -> Database:
    """初始化数据库"""
    global _db
    _db = Database(database_url)
    return _db
