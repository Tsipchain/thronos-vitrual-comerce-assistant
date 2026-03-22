from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class Order(BaseModel):
    __tablename__ = "orders"

    shop_id = Column(String(36), nullable=False, index=True)
    customer_id = Column(String(36), nullable=False, index=True)
    order_number = Column(String(50), unique=True, nullable=False, index=True)

    status = Column(
        String(30), default="pending", nullable=False, index=True
    )  # pending, confirmed, processing, shipped, delivered, cancelled

    total_amount = Column(Float, nullable=False, default=0.0)
    discount_amount = Column(Float, default=0.0)
    shipping_cost = Column(Float, default=0.0)
    currency = Column(String(3), default="EUR")

    shipping_method = Column(String(100), nullable=True)
    tracking_number = Column(String(255), nullable=True)
    shipping_address = Column(JSON, nullable=True)
    billing_address = Column(JSON, nullable=True)

    payment_method = Column(String(50), nullable=True)
    payment_status = Column(String(30), default="pending")
    voucher_code = Column(String(50), nullable=True)

    notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)

    confirmed_at = Column(DateTime, nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)


class OrderItem(BaseModel):
    __tablename__ = "order_items"

    order_id = Column(String(36), nullable=False, index=True)
    product_id = Column(String(36), nullable=False)
    sku = Column(String(100), nullable=True)
    product_name = Column(String(255), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
