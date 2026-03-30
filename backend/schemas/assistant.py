from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    role: str = "customer"  # "customer" or "merchant"; overridden by JWT role if present
    context: Optional[dict] = None  # optional extra context (e.g. current page, selected order)


class SuggestedAction(BaseModel):
    label: str
    action: str  # e.g. "view_order", "approve_return", "check_stock"
    params: dict = {}


class ChatResponse(BaseModel):
    response: str
    data: Optional[dict] = None
    suggested_actions: list[SuggestedAction] = []
    intent: Optional[str] = None
