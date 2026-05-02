import logging

from fastapi import HTTPException, status

import services.database as _db_svc

logger = logging.getLogger(__name__)


async def get_db():
    if _db_svc.async_session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized — service starting up, please retry",
        )
    # Wrap the entire session lifecycle so any cleanup exception (rollback/close
    # failing on a dead connection) still produces a clean HTTP response rather
    # than dropping the TCP connection (which Railway logs as 502).
    try:
        async with _db_svc.async_session() as session:
            yield session
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[get_db] session error — DB connection may be unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable — please retry",
        )
