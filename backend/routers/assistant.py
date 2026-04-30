import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id, get_current_user
from dependencies.database import get_db
from schemas.assistant import ChatRequest, ChatResponse
from services.ai_assistant import CommerceAssistant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

# Total budget for one chat turn (includes DB lookups + AI call).
_CHAT_TIMEOUT = 25.0


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    role      = current_user.get("role", request.role)
    assistant = CommerceAssistant(db)

    try:
        result = await asyncio.wait_for(
            assistant.process_message(shop_id, request.message, request.context, role=role),
            timeout=_CHAT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(
            "[assistant] chat timeout shop=%s role=%s timeout_s=%.1f",
            shop_id, role, _CHAT_TIMEOUT,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Assistant timed out — please retry",
        )
    except Exception as exc:
        logger.error(
            "[assistant] chat error shop=%s role=%s reason=%s",
            shop_id, role, type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Assistant temporarily unavailable",
        )

    return ChatResponse(**result)
