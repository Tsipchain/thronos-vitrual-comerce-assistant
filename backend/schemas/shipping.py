from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ShippingLabelCreate(BaseModel):
    order_id: str
    carrier: str
    label_type: str = "shipping"
    sender_address: Optional[dict] = None
    recipient_address: Optional[dict] = None
    weight_kg: Optional[float] = None
    dimensions: Optional[dict] = None
    packing_instructions: Optional[str] = None


class ShippingLabelResponse(BaseModel):
    id: str
    shop_id: str
    order_id: str
    return_request_id: Optional[str] = None
    carrier: str
    tracking_number: Optional[str] = None
    label_url: Optional[str] = None
    label_type: str
    status: str
    weight_kg: Optional[float] = None
    dimensions: Optional[dict] = None
    packing_instructions: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PackingInstructionsResponse(BaseModel):
    order_id: str
    items: list[dict]
    instructions: str
    special_notes: Optional[str] = None


class CourierSummary(BaseModel):
    carrier: str
    total_shipments: int
    labels: list[dict]
