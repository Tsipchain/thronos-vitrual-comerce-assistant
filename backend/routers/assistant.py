import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id, get_current_user
from dependencies.database import get_db
from schemas.assistant import ChatRequest, ChatResponse
from services.ai_assistant import CommerceAssistant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    # JWT role takes precedence over request body role
    role = current_user.get("role", request.role)
    assistant = CommerceAssistant(db)
    result = await assistant.process_message(shop_id, request.message, request.context, role=role)
    return ChatResponse(**result)
