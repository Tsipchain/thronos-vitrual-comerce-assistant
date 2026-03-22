from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: list = []
    price: float
    cost_price: Optional[float] = None
    currency: str = "EUR"
    stock_quantity: int = 0
    low_stock_threshold: int = 5
    images: list = []
    weight_kg: Optional[float] = None
    dimensions: Optional[dict] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list] = None
    price: Optional[float] = None
    cost_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    images: Optional[list] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: str
    shop_id: str
    sku: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: list = []
    price: float
    cost_price: Optional[float] = None
    currency: str
    stock_quantity: int
    low_stock_threshold: int
    available_stock: int = 0
    is_low_stock: bool = False
    is_dead_stock: bool = False
    total_sold: int = 0
    total_returned: int = 0
    last_sold_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class StockUpdateRequest(BaseModel):
    quantity: int
    reason: Optional[str] = None
