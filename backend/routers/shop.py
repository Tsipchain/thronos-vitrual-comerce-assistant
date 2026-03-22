import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_user, get_current_shop_id
from dependencies.database import get_db
from models.shop import Shop
from schemas.shop import ShopResponse, ShopUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/shop", tags=["shop"])


@router.get("/", response_model=ShopResponse)
async def get_shop(shop_id: str = Depends(get_current_shop_id), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.put("/", response_model=ShopResponse)
async def update_shop(
    data: ShopUpdate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(shop, field, value)
    await db.commit()
    await db.refresh(shop)
    return shop
