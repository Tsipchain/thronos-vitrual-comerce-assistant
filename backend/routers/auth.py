import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
    """Simple login — creates shop if needed."""
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
        logger.info("[auth] new shop created shop_id=%s", shop.id)
    else:
        user_id = shop.owner_id

    token = create_access_token(user_id=user_id, email=request.email, shop_id=shop.id)
    return TokenResponse(access_token=token, user_id=user_id, shop_id=shop.id)


class CustomerTokenRequest(BaseModel):
    commerce_tenant_id: str
    customer_id: str | None = None
    customer_email: str | None = None


# DB lookup budget: must finish well within the commerce-side axios timeout (15 s).
_DB_TIMEOUT = float(os.getenv("VCA_AUTH_DB_TIMEOUT_S", "8"))


@router.post("/customer-token", response_model=TokenResponse)
async def customer_token(
    request: CustomerTokenRequest,
    db: AsyncSession = Depends(get_db),
    x_thronos_commerce_key: str | None = Header(default=None, alias="X-Thronos-Commerce-Key"),
) -> TokenResponse:
    """
    Issue a scoped customer JWT for a commerce tenant’s storefront widget.

    Auth: X-Thronos-Commerce-Key must match THRONOS_COMMERCE_API_KEY env var.
    When THRONOS_COMMERCE_API_KEY is absent the check is skipped (dev mode).
    """
    tenant_id = request.commerce_tenant_id  # logged throughout — not a secret

    # --- key check (never log the key value) ---
    expected_key = os.getenv("THRONOS_COMMERCE_API_KEY", "").strip()
    if expected_key:
        if not x_thronos_commerce_key or x_thronos_commerce_key != expected_key:
            logger.warning(
                "[auth] customer-token rejected tenant=%s reason=invalid_commerce_key",
                tenant_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid commerce key",
            )
    else:
        logger.warning(
            "[auth] THRONOS_COMMERCE_API_KEY not set — skipping key check (dev mode)"
        )

    # --- shop lookup with timeout ---
    try:
        result = await asyncio.wait_for(
            db.execute(select(Shop).where(Shop.commerce_tenant_id == tenant_id)),
            timeout=_DB_TIMEOUT,
        )
        shop = result.scalar_one_or_none()
    except asyncio.TimeoutError:
        logger.error(
            "[auth] customer-token DB timeout tenant=%s timeout_s=%.1f",
            tenant_id, _DB_TIMEOUT,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shop lookup timed out — please retry",
        )
    except Exception as exc:
        logger.error(
            "[auth] customer-token DB error tenant=%s reason=%s",
            tenant_id, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shop lookup failed",
        )

    if not shop:
        logger.warning(
            "[auth] customer-token not_found tenant=%s", tenant_id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No shop linked to commerce_tenant_id={tenant_id!r}",
        )

    customer_id = request.customer_id or str(uuid.uuid4())
    token = create_access_token(
        user_id=customer_id,
        email=request.customer_email or "",
        role="customer",
        shop_id=shop.id,
    )
    logger.info(
        "[auth] customer-token issued tenant=%s shop=%s", tenant_id, shop.id
    )
    return TokenResponse(access_token=token, user_id=customer_id, shop_id=shop.id)
