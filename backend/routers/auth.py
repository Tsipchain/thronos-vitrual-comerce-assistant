import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.database import get_db
from models.shop import Shop
from services.auth import create_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: str
    shop_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    shop_id: str


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Simple login - creates shop if needed. In production, integrate with Thronos auth."""
    result = await db.execute(
        select(Shop).where(Shop.owner_email == request.email)
    )
    shop = result.scalar_one_or_none()
    if not shop:
        user_id = str(uuid.uuid4())
        shop = Shop(
            name=request.shop_name or f"{request.email}'s Shop",
            owner_id=user_id,
            owner_email=request.email,
        )
        db.add(shop)
        await db.commit()
        await db.refresh(shop)
        logger.info(f"New shop created: {shop.id} for {request.email}")
    else:
        user_id = shop.owner_id

    token = create_access_token(user_id=user_id, email=request.email, shop_id=shop.id)
    return TokenResponse(access_token=token, user_id=user_id, shop_id=shop.id)
