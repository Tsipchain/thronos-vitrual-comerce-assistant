from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class VoucherCreate(BaseModel):
    customer_id: Optional[str] = None
    type: str  # percentage, fixed, credit_note, free_shipping
    value: float
    currency: str = "EUR"
    min_order_amount: float = 0.0
    max_discount_amount: Optional[float] = None
    applicable_categories: list = []
    applicable_products: list = []
    max_uses: int = 1
    max_uses_per_customer: int = 1
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class VoucherValidateRequest(BaseModel):
    code: str
    order_amount: float
    customer_id: Optional[str] = None


class VoucherValidateResponse(BaseModel):
    valid: bool
    discount_amount: float = 0.0
    message: str


class VoucherResponse(BaseModel):
    id: str
    shop_id: str
    customer_id: Optional[str] = None
    code: str
    type: str
    value: float
    currency: str
    min_order_amount: float
    max_uses: int
    current_uses: int
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: bool
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True
