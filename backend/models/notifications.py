from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class Notification(BaseModel):
    __tablename__ = "notifications"

    shop_id = Column(String(36), nullable=False, index=True)
    type = Column(String(20), nullable=False)  # email, sms, push
    recipient = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)

    status = Column(String(20), default="pending")  # pending, sent, failed
    triggered_by = Column(String(100), nullable=True)  # low_stock, return_opened, voucher_created, etc.
    reference_id = Column(String(36), nullable=True)   # linked entity id
    reference_type = Column(String(50), nullable=True)  # order, return, voucher, product

    # Renamed from `metadata` — that name is reserved by SQLAlchemy DeclarativeBase.
    # DB column name is kept as "metadata" so existing tables need no migration.
    extra_metadata = Column("metadata", JSON, default=dict)
    error_message = Column(Text, nullable=True)
