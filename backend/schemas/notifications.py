from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    type: str  # email, sms, push
    recipient: str
    subject: Optional[str] = None
    body: str
    triggered_by: Optional[str] = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None


class NotificationResponse(BaseModel):
    id: str
    shop_id: str
    type: str
    recipient: str
    subject: Optional[str] = None
    body: str
    status: str
    triggered_by: Optional[str] = None
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
