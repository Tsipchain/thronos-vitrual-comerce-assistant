import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from schemas.assistant import ChatRequest, ChatResponse
from services.ai_assistant import CommerceAssistant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    assistant = CommerceAssistant(db)
    result = await assistant.process_message(shop_id, request.message, request.context)
    return ChatResponse(**result)
