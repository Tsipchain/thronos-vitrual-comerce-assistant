import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from models.base import Base

logger = logging.getLogger(__name__)

_engine = None
async_session: async_sessionmaker[AsyncSession] | None = None


def _get_db_url() -> str:
    url = settings.database_url
    if not url:
        logger.warning("DATABASE_URL not set – falling back to in-memory SQLite")
        return "sqlite+aiosqlite://"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


async def initialize_database():
    global _engine, async_session
    db_url = _get_db_url()
    is_sqlite = db_url.startswith("sqlite")

    _engine = create_async_engine(
        db_url,
        echo=settings.debug,
        **({"connect_args": {"check_same_thread": False}} if is_sqlite else {"pool_size": 10, "max_overflow": 20}),
    )
    async_session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")


async def close_database():
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database connections closed")
