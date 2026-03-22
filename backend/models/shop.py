from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class Shop(BaseModel):
    __tablename__ = "shops"

    name = Column(String(255), nullable=False)
    owner_id = Column(String(36), nullable=False, index=True)
    owner_email = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    # Policies
    return_policy_text = Column(Text, nullable=True)
    return_window_days = Column(Integer, default=14)
    voucher_rules = Column(JSON, default=dict)

    # Shipping & operations
    shipping_methods = Column(JSON, default=list)
    operating_hours = Column(JSON, default=dict)
    sla_hours = Column(Integer, default=48)

    # Notifications
    notification_preferences = Column(JSON, default=dict)

    # Templates
    email_templates = Column(JSON, default=dict)
    sms_templates = Column(JSON, default=dict)

    is_active = Column(Boolean, default=True)
