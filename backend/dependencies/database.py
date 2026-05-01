from fastapi import HTTPException, status

import services.database as _db_svc


async def get_db():
    if _db_svc.async_session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not initialized — service starting up, please retry",
        )
    async with _db_svc.async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
