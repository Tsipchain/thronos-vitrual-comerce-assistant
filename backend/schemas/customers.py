from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CustomerCreate(BaseModel):
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    tags: list = []
    notes: Optional[str] = None
    default_address: Optional[dict] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    tags: Optional[list] = None
    notes: Optional[str] = None
    default_address: Optional[dict] = None
    is_blocked: Optional[bool] = None


class CustomerResponse(BaseModel):
    id: str
    shop_id: str
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    total_orders: int
    total_returns: int
    total_spent: float
    total_refunded: float
    currency: str
    risk_score: float
    tags: list
    notes: Optional[str] = None
    last_order_at: Optional[datetime] = None
    is_blocked: bool
    created_at: datetime

    class Config:
        from_attributes = True
