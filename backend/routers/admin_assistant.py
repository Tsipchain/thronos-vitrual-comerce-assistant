import logging

from fastapi import APIRouter, Header, HTTPException, status

from core.config import settings
from schemas.admin_assistant import AdminChatRequest, AdminChatResponse
from services.admin_assistant_service import AdminAssistantService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/assistant", tags=["admin-assistant"])

_service = AdminAssistantService()


def _require_commerce_key(x_thronos_commerce_key: str | None) -> None:
    """Validate the server-to-server shared secret sent by the commerce server."""
    secret = settings.commerce_webhook_secret
    if not secret or x_thronos_commerce_key != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Thronos-Commerce-Key",
        )


@router.post("/chat", response_model=AdminChatResponse)
async def admin_assistant_chat(
    request: AdminChatRequest,
    x_thronos_commerce_key: str | None = Header(default=None),
) -> AdminChatResponse:
    """
    Tenant-admin AI assistant endpoint.

    Called server-to-server by the commerce platform on behalf of a logged-in
    tenant admin. Auth is via the shared COMMERCE_WEBHOOK_SECRET header.
    The assistant only sees and proposes changes for the tenant in the request.
    """
    _require_commerce_key(x_thronos_commerce_key)

    tenant_id = request.tenant_context.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required in tenant_context")

    logger.info(
        "Admin assistant chat: tenant=%s section=%s msg_len=%d",
        tenant_id,
        request.section,
        len(request.message),
    )

    result = await _service.process_message(
        message=request.message,
        tenant_context=request.tenant_context.model_dump(),
        section=request.section,
        conversation_history=[m.model_dump() for m in request.conversation_history],
    )

    return AdminChatResponse(**result)
