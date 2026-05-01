import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from dependencies.database import get_db
from models.shop import Shop

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

# DB lookup budget well within the commerce-side axios timeout (15 s).
_DB_TIMEOUT = float(os.getenv("VCA_AUTH_DB_TIMEOUT_S", "8"))


# ---------------------------------------------------------------------------
# Shared-secret resolution
# ---------------------------------------------------------------------------

def _resolve_shared_secret() -> tuple[str, str]:
    """Return (secret, source_name). Never log the secret value."""
    primary = (getattr(settings, "commerce_webhook_secret", "") or "").strip()
    if primary:
        return primary, "COMMERCE_WEBHOOK_SECRET"
    fallback = os.getenv("ASSISTANT_WEBHOOK_SECRET", "").strip()
    if fallback:
        return fallback, "ASSISTANT_WEBHOOK_SECRET"
    return "", "none"


# ---------------------------------------------------------------------------
# JWT signing — inline, no dependency on services.auth
# ---------------------------------------------------------------------------

def _sign_jwt(
    user_id: str,
    email: str,
    role: str,
    shop_id: str | None,
    expiry_minutes: int,
) -> tuple[str, int]:
    """Return (token, expires_in_seconds). Raises HTTPException 500 on failure."""
    jwt_secret = (getattr(settings, "jwt_secret_key", "") or "").strip()
    if not jwt_secret:
        logger.error(
            "[auth] JWT_SECRET_KEY not configured — cannot sign token"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT signing key not configured on this server",
        )

    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "shop_id": shop_id,
        "exp": now + timedelta(minutes=expiry_minutes),
        "iat": now,
    }

    try:
        from jose import jwt as jose_jwt
        token = jose_jwt.encode(payload, jwt_secret, algorithm="HS256")
    except Exception as exc:
        logger.error("[auth] JWT encode failed reason=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sign token",
        )

    return token, expiry_minutes * 60


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    shop_name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    shop_id: str


class CustomerTokenRequest(BaseModel):
    commerce_tenant_id: str
    customer_id: str | None = None
    customer_email: str | None = None


class CustomerTokenResponse(BaseModel):
    ok: bool = True
    token: str
    expiresIn: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Simple login — creates shop if needed."""
    from services.auth import create_access_token

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


@router.post("/customer-token", response_model=CustomerTokenResponse)
async def customer_token(
    request_body: CustomerTokenRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    x_thronos_commerce_key: str | None = Header(default=None, alias="X-Thronos-Commerce-Key"),
) -> CustomerTokenResponse:
    """Issue a scoped customer JWT for a commerce tenant's storefront widget.

    Lightweight — no LLM calls.
    Auth: X-Thronos-Commerce-Key resolved via COMMERCE_WEBHOOK_SECRET → ASSISTANT_WEBHOOK_SECRET.
    Wrong key → 401. Missing JWT_SECRET_KEY → 500. DB down → 503.
    """
    tenant_id = request_body.commerce_tenant_id
    host = http_request.headers.get("host", "-")

    # --- shared-secret check (log source name only, never the value) ---
    try:
        expected_key, secret_source = _resolve_shared_secret()
    except Exception as exc:
        logger.error(
            "[auth] customer-token secret resolution failed tenantId=%s host=%s reason=%s",
            tenant_id, host, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        )

    logger.info(
        "[auth] customer-token hit tenantId=%s host=%s secretSource=%s "
        "jwt_secret_present=%s",
        tenant_id, host, secret_source,
        bool((getattr(settings, "jwt_secret_key", "") or "").strip()),
    )

    if expected_key:
        if not x_thronos_commerce_key or x_thronos_commerce_key.strip() != expected_key:
            logger.warning(
                "[auth] customer-token rejected tenantId=%s host=%s "
                "reason=invalid_key secretSource=%s",
                tenant_id, host, secret_source,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid commerce key",
            )
    else:
        logger.warning(
            "[auth] no shared secret configured (secretSource=none) "
            "— key check skipped (dev mode)"
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
            "[auth] customer-token DB timeout tenantId=%s timeout_s=%.1f reason=timeout",
            tenant_id, _DB_TIMEOUT,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shop lookup timed out — please retry",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[auth] customer-token DB error tenantId=%s reason=%s",
            tenant_id, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Shop lookup failed",
        )

    if not shop:
        logger.warning(
            "[auth] customer-token tenantId=%s reason=not_found",
            tenant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No shop linked to commerce_tenant_id={tenant_id!r}. "
                   "Register the shop in VCA first.",
        )

    # --- sign token ---
    customer_id = request_body.customer_id or str(uuid.uuid4())
    expiry_minutes = int(getattr(settings, "jwt_expiration_minutes", 1440))
    raw_token, expires_in = _sign_jwt(
        user_id=customer_id,
        email=request_body.customer_email or "",
        role="customer",
        shop_id=shop.id,
        expiry_minutes=expiry_minutes,
    )

    logger.info(
        "[auth] customer-token issued tenantId=%s shop=%s expiresIn=%d",
        tenant_id, shop.id, expires_in,
    )
    return CustomerTokenResponse(ok=True, token=raw_token, expiresIn=expires_in)
