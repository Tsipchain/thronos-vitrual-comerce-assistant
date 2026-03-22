from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class Customer(BaseModel):
    __tablename__ = "customers"

    shop_id = Column(String(36), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)

    total_orders = Column(Integer, default=0)
    total_returns = Column(Integer, default=0)
    total_spent = Column(Float, default=0.0)
    total_refunded = Column(Float, default=0.0)
    currency = Column(String(3), default="EUR")

    risk_score = Column(Float, default=0.0)  # 0.0 (trusted) to 1.0 (high risk)
    tags = Column(JSON, default=list)
    notes = Column(Text, nullable=True)

    default_address = Column(JSON, nullable=True)
    last_order_at = Column(DateTime, nullable=True)
    first_order_at = Column(DateTime, nullable=True)

    is_blocked = Column(Boolean, default=False)
