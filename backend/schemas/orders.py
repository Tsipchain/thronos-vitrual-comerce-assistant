from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int = 1


class OrderCreate(BaseModel):
    customer_id: str
    items: list[OrderItemCreate]
    shipping_method: Optional[str] = None
    shipping_address: Optional[dict] = None
    billing_address: Optional[dict] = None
    payment_method: Optional[str] = None
    voucher_code: Optional[str] = None
    notes: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    status: str
    tracking_number: Optional[str] = None
    internal_notes: Optional[str] = None


class OrderItemResponse(BaseModel):
    id: str
    product_id: str
    sku: Optional[str] = None
    product_name: str
    quantity: int
    unit_price: float
    total_price: float

    class Config:
        from_attributes = True


class OrderResponse(BaseModel):
    id: str
    shop_id: str
    customer_id: str
    order_number: str
    status: str
    total_amount: float
    discount_amount: float
    shipping_cost: float
    currency: str
    shipping_method: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_address: Optional[dict] = None
    payment_method: Optional[str] = None
    payment_status: str
    voucher_code: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    total: int
    page: int
    per_page: int
