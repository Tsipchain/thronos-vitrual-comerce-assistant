from typing import Any, Optional

from pydantic import BaseModel, Field


class TenantContext(BaseModel):
    tenant_id: str
    store_name: Any  # str or dict with lang keys e.g. {"el": "...", "en": "..."}
    theme: dict = {}
    branding: dict = {}
    homepage: dict = {}
    notifications: dict = {}
    assistant: dict = {}
    payments_summary: dict = {}
    footer: dict = {}
    categories_count: int = 0
    products_count: int = 0
    allowed_theme_keys: list[str] = []
    support_tier: str = "SELF_SERVICE"


class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class AdminChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    tenant_context: TenantContext
    section: Optional[str] = None  # e.g. "branding", "homepage", "products", "payments", "notifications", "assistant"
    conversation_history: list[ConversationMessage] = Field(default_factory=list)


class ProposedPatch(BaseModel):
    field_path: str  # dot-notated path in tenant config, e.g. "theme.buttonRadius"
    current_value: Any = None
    proposed_value: Any
    description: str
    requires_password: bool = False


class AdminChatResponse(BaseModel):
    response: str
    proposed_patches: list[ProposedPatch] = []
    intent: Optional[str] = None
