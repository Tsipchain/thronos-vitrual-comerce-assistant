from sqlalchemy import Column, Float, String, Text
from sqlalchemy.dialects.postgresql import JSON

from models.base import BaseModel


class ShippingLabel(BaseModel):
    __tablename__ = "shipping_labels"

    shop_id = Column(String(36), nullable=False, index=True)
    order_id = Column(String(36), nullable=False, index=True)
    return_request_id = Column(String(36), nullable=True)

    carrier = Column(String(100), nullable=False)  # acs, elta, speedex, dhl, ups, fedex, generic
    tracking_number = Column(String(255), nullable=True, index=True)
    label_url = Column(String(500), nullable=True)
    label_type = Column(String(20), nullable=False, default="shipping")  # shipping, return

    status = Column(String(30), default="created")  # created, printed, in_transit, delivered, returned

    sender_address = Column(JSON, nullable=True)
    recipient_address = Column(JSON, nullable=True)

    weight_kg = Column(Float, nullable=True)
    dimensions = Column(JSON, nullable=True)  # {length, width, height}
    packing_instructions = Column(Text, nullable=True)

    courier_reference = Column(String(255), nullable=True)
    courier_response = Column(JSON, nullable=True)
