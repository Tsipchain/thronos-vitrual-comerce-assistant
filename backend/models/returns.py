from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class ReturnRequest(BaseModel):
    __tablename__ = "return_requests"

    shop_id = Column(String(36), nullable=False, index=True)
    order_id = Column(String(36), nullable=False, index=True)
    customer_id = Column(String(36), nullable=False, index=True)

    status = Column(
        String(30), default="pending", nullable=False, index=True
    )  # pending, approved, rejected, completed

    reason = Column(Text, nullable=False)
    reason_category = Column(String(50), nullable=True)  # defective, wrong_item, not_as_described, changed_mind, other

    items = Column(JSON, default=list)  # [{product_id, quantity, reason}]

    refund_type = Column(String(30), nullable=True)  # voucher, refund, credit_note, exchange
    refund_amount = Column(Float, default=0.0)
    currency = Column(String(3), default="EUR")

    admin_notes = Column(Text, nullable=True)
    ai_recommendation = Column(Text, nullable=True)
    risk_score = Column(Float, default=0.0)  # 0.0 (safe) to 1.0 (suspicious)

    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(36), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
