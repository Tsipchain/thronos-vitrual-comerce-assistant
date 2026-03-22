from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReturnItemRequest(BaseModel):
    product_id: str
    quantity: int = 1
    reason: Optional[str] = None


class ReturnCreate(BaseModel):
    order_id: str
    reason: str
    reason_category: Optional[str] = None
    items: list[ReturnItemRequest] = []
    refund_type: Optional[str] = None  # voucher, refund, credit_note, exchange


class ReturnDecision(BaseModel):
    action: str  # approve, reject
    refund_type: Optional[str] = None
    refund_amount: Optional[float] = None
    admin_notes: Optional[str] = None
    rejected_reason: Optional[str] = None


class ReturnResponse(BaseModel):
    id: str
    shop_id: str
    order_id: str
    customer_id: str
    status: str
    reason: str
    reason_category: Optional[str] = None
    items: list = []
    refund_type: Optional[str] = None
    refund_amount: float
    currency: str
    admin_notes: Optional[str] = None
    ai_recommendation: Optional[str] = None
    risk_score: float
    created_at: datetime
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
