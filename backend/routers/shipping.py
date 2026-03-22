import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.shipping import ShippingLabel
from schemas.shipping import ShippingLabelCreate, ShippingLabelResponse, PackingInstructionsResponse
from services.shipping import ShippingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/shipping", tags=["shipping"])


@router.get("/labels", response_model=list[ShippingLabelResponse])
async def list_labels(
    order_id: str | None = None,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(ShippingLabel).where(ShippingLabel.shop_id == shop_id)
    if order_id:
        query = query.where(ShippingLabel.order_id == order_id)
    query = query.order_by(ShippingLabel.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/labels", response_model=ShippingLabelResponse, status_code=201)
async def create_label(
    data: ShippingLabelCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ShippingService(db)
    try:
        return await svc.create_shipping_label(
            shop_id=shop_id, order_id=data.order_id, carrier=data.carrier,
            sender_address=data.sender_address, recipient_address=data.recipient_address,
            weight_kg=data.weight_kg, dimensions=data.dimensions,
            packing_instructions=data.packing_instructions,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/packing/{order_id}", response_model=PackingInstructionsResponse)
async def get_packing_instructions(
    order_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ShippingService(db)
    try:
        return await svc.generate_packing_instructions(order_id, shop_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/courier-summary")
async def courier_summary(
    order_ids: list[str],
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    svc = ShippingService(db)
    return await svc.prepare_courier_summary(shop_id, order_ids)
