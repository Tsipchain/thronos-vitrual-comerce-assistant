import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy import select
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


class CustomerTokenRequest(BaseModel):
    commerce_tenant_id: str
    customer_id: str | None = None
    customer_email: str | None = None


@router.post("/customer-token", response_model=TokenResponse)
async def customer_token(
    request: CustomerTokenRequest,
    db: AsyncSession = Depends(get_db),
    x_thronos_commerce_key: str | None = Header(default=None, alias="X-Thronos-Commerce-Key"),
):
    """Issue a scoped customer JWT for a commerce tenant's storefront widget.

    Requires the caller to supply the shared secret via X-Thronos-Commerce-Key.
    Set THRONOS_COMMERCE_API_KEY on this service to enable the check.
    If the env var is absent the check is skipped with a warning (dev mode).
    """
    expected_key = os.getenv("THRONOS_COMMERCE_API_KEY", "").strip()
    if expected_key:
        if not x_thronos_commerce_key or x_thronos_commerce_key != expected_key:
            logger.warning(
                "[auth] /customer-token rejected — invalid or missing X-Thronos-Commerce-Key"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid commerce key",
            )
    else:
        logger.warning(
            "[auth] THRONOS_COMMERCE_API_KEY not set — skipping commerce-key check (dev mode)"
        )

    result = await db.execute(
        select(Shop).where(Shop.commerce_tenant_id == request.commerce_tenant_id)
    )
    shop = result.scalar_one_or_none()
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No shop linked to commerce_tenant_id={request.commerce_tenant_id!r}",
        )
    customer_id = request.customer_id or str(uuid.uuid4())
    token = create_access_token(
        user_id=customer_id,
        email=request.customer_email or "",
        role="customer",
        shop_id=shop.id,
    )
    return TokenResponse(access_token=token, user_id=customer_id, shop_id=shop.id)
