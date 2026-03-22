import secrets

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


def generate_voucher_code() -> str:
    return "TH-" + secrets.token_hex(4).upper()


class Voucher(BaseModel):
    __tablename__ = "vouchers"

    shop_id = Column(String(36), nullable=False, index=True)
    customer_id = Column(String(36), nullable=True, index=True)
    code = Column(String(50), unique=True, nullable=False, default=generate_voucher_code, index=True)

    type = Column(String(30), nullable=False)  # percentage, fixed, credit_note, free_shipping
    value = Column(Float, nullable=False, default=0.0)
    currency = Column(String(3), default="EUR")

    min_order_amount = Column(Float, default=0.0)
    max_discount_amount = Column(Float, nullable=True)
    applicable_categories = Column(JSON, default=list)
    applicable_products = Column(JSON, default=list)

    max_uses = Column(Integer, default=1)
    current_uses = Column(Integer, default=0)
    max_uses_per_customer = Column(Integer, default=1)

    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)

    created_by = Column(String(30), default="manual")  # manual, system, return, promotion
    return_request_id = Column(String(36), nullable=True)

    is_active = Column(Boolean, default=True)

    @property
    def is_fully_used(self) -> bool:
        return self.current_uses >= self.max_uses

    @property
    def is_valid(self) -> bool:
        from datetime import datetime
        now = datetime.utcnow()
        if not self.is_active or self.is_fully_used:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True
