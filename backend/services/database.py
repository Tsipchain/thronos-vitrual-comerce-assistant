import logging
import os

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from models.base import Base

logger = logging.getLogger(__name__)

_engine = None
async_session: async_sessionmaker[AsyncSession] | None = None

# Railway PostgreSQL plugin can expose the connection string under several names.
# We check them in priority order so any of them works without extra configuration.
_RAILWAY_DB_ENV_VARS = [
    "DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_PRIVATE_URL",
    "DATABASE_PUBLIC_URL",
]


def _normalize_scheme(url: str) -> str:
    """Convert postgres:// or postgresql:// to postgresql+asyncpg://."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+" not in url.split("://")[0]:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _get_db_url() -> str:
    """
    Resolve the database URL from environment variables.

    Checks the following vars in order (first non-empty value wins):
      DATABASE_URL, POSTGRES_URL, DATABASE_PRIVATE_URL, DATABASE_PUBLIC_URL

    Normalises the scheme to postgresql+asyncpg:// and pre-validates the URL
    with SQLAlchemy's make_url() so failures are caught here with a clear
    message rather than deep inside create_async_engine.
    """
    raw_url: str | None = None
    source_var: str | None = None

    # settings.database_url covers DATABASE_URL via pydantic-settings;
    # the rest we read directly from os.environ.
    pydantic_candidates = {
        "DATABASE_URL": settings.database_url,
        "POSTGRES_URL": settings.postgres_url,
        "DATABASE_PRIVATE_URL": settings.database_private_url,
        "DATABASE_PUBLIC_URL": settings.database_public_url,
    }

    for var_name in _RAILWAY_DB_ENV_VARS:
        # Prefer the pydantic-resolved value (respects .env file), fall back to raw env.
        value = pydantic_candidates.get(var_name) or os.environ.get(var_name)
        if value and value.strip():
            raw_url = value.strip()
            source_var = var_name
            break

    if not raw_url:
        logger.warning(
            "No database URL found in any of: %s – "
            "falling back to in-memory SQLite (data will NOT persist across restarts). "
            "Set one of those env vars to a PostgreSQL connection string.",
            ", ".join(_RAILWAY_DB_ENV_VARS),
        )
        return "sqlite+aiosqlite://"

    normalised = _normalize_scheme(raw_url)

    # Pre-validate before handing to SQLAlchemy so the error is actionable.
    try:
        make_url(normalised)
    except ArgumentError as exc:
        raise RuntimeError(
            f"The database URL from env var '{source_var}' is not a valid SQLAlchemy URL.\n"
            f"  Raw value    : {raw_url!r}\n"
            f"  Normalised   : {normalised!r}\n"
            f"  Error        : {exc}\n"
            "  Expected format: postgresql+asyncpg://user:password@host:port/dbname\n"
            "  Fix: set DATABASE_URL (or POSTGRES_URL) to a valid PostgreSQL connection string."
        ) from exc

    scheme = normalised.split("://")[0]
    logger.info("Database URL resolved from %s (scheme=%s)", source_var, scheme)
    return normalised


async def initialize_database():
    global _engine, async_session
    db_url = _get_db_url()
    is_sqlite = db_url.startswith("sqlite")

    _engine = create_async_engine(
        db_url,
        echo=settings.debug,
        **(
            {"connect_args": {"check_same_thread": False}}
            if is_sqlite
            else {"pool_size": 10, "max_overflow": 20}
        ),
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
