from datetime import datetime, timedelta

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class Product(BaseModel):
    __tablename__ = "products"

    shop_id = Column(String(36), nullable=False, index=True)
    sku = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    tags = Column(JSON, default=list)

    price = Column(Float, nullable=False, default=0.0)
    cost_price = Column(Float, nullable=True)
    currency = Column(String(3), default="EUR")

    stock_quantity = Column(Integer, default=0)
    low_stock_threshold = Column(Integer, default=5)
    reserved_quantity = Column(Integer, default=0)

    images = Column(JSON, default=list)
    weight_kg = Column(Float, nullable=True)
    dimensions = Column(JSON, nullable=True)

    last_sold_at = Column(DateTime, nullable=True)
    total_sold = Column(Integer, default=0)
    total_returned = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)

    @property
    def is_low_stock(self) -> bool:
        return self.stock_quantity <= self.low_stock_threshold

    @property
    def available_stock(self) -> int:
        return max(0, self.stock_quantity - self.reserved_quantity)

    @property
    def is_dead_stock(self) -> bool:
        if self.last_sold_at is None:
            age = (datetime.utcnow() - self.created_at).days if self.created_at else 999
            return age > 90
        return (datetime.utcnow() - self.last_sold_at) > timedelta(days=90)
