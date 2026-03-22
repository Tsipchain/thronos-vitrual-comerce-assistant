from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ShopCreate(BaseModel):
    name: str
    owner_email: str
    domain: Optional[str] = None
    description: Optional[str] = None
    return_policy_text: Optional[str] = None
    return_window_days: int = 14
    voucher_rules: dict = {}
    shipping_methods: list = []
    operating_hours: dict = {}
    sla_hours: int = 48
    notification_preferences: dict = {}
    email_templates: dict = {}
    sms_templates: dict = {}


class ShopUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    description: Optional[str] = None
    return_policy_text: Optional[str] = None
    return_window_days: Optional[int] = None
    voucher_rules: Optional[dict] = None
    shipping_methods: Optional[list] = None
    operating_hours: Optional[dict] = None
    sla_hours: Optional[int] = None
    notification_preferences: Optional[dict] = None
    email_templates: Optional[dict] = None
    sms_templates: Optional[dict] = None


class ShopResponse(BaseModel):
    id: str
    name: str
    owner_id: str
    owner_email: str
    domain: Optional[str] = None
    description: Optional[str] = None
    return_policy_text: Optional[str] = None
    return_window_days: int
    shipping_methods: list
    operating_hours: dict
    sla_hours: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
