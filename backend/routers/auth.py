"""
POST /api/v1/auth/customer-token

Server-to-server endpoint — no LLM calls, no AI dependencies.
Commerce calls this to get a short-lived JWT for a storefront session.

Auth:   X-Thronos-Commerce-Key header matched against COMMERCE_WEBHOOK_SECRET
        (fallback: ASSISTANT_WEBHOOK_SECRET for legacy compatibility).
JWT:    signed with JWT_SECRET_KEY (fallback: JWT_SECRET).
Body:   { "tenantId": "...", "host": "...", "lang": "..." }
Return: { "token": "...", "expiresIn": <seconds> }
"""
import logging
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from dependencies.database import get_db
from models.shop import Shop

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


# ---------------------------------------------------------------------------
# Secret / key resolution helpers
# ---------------------------------------------------------------------------

def _resolve_shared_secret() -> tuple[str, str]:
    """Return (expected_secret, source_name). Never log the value."""
    primary = (getattr(settings, "commerce_webhook_secret", "") or "").strip()
    if primary:
        return primary, "COMMERCE_WEBHOOK_SECRET"
    fallback = os.getenv("ASSISTANT_WEBHOOK_SECRET", "").strip()
    if fallback:
        return fallback, "ASSISTANT_WEBHOOK_SECRET"
    return "", "none"


def _resolve_jwt_secret() -> tuple[str, str]:
    """Return (jwt_secret, source_name). JWT_SECRET_KEY first, JWT_SECRET fallback."""
    # Try settings attribute (pydantic-settings reads JWT_SECRET_KEY from env)
    primary = (getattr(settings, "jwt_secret_key", "") or "").strip()
    if primary:
        return primary, "JWT_SECRET_KEY"
    # Raw env fallback in case the var is named JWT_SECRET
    fallback = os.getenv("JWT_SECRET", "").strip()
    if fallback:
        return fallback, "JWT_SECRET"
    return "", "none"


def _sign_customer_jwt(
    customer_id: str,
    tenant_id: str,
    shop_id: str | None,
    expiry_minutes: int,
) -> tuple[str, int]:
    """Sign and return (token, expires_in_seconds). Raises HTTPException 500 on failure."""
    jwt_secret, jwt_source = _resolve_jwt_secret()
    if not jwt_secret:
        logger.error(
            "[auth] customer-token JWT secret missing — set JWT_SECRET_KEY or JWT_SECRET"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT signing key not configured on this server",
        )

    now = datetime.utcnow()
    payload = {
        "sub": customer_id,
        "role": "customer",
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "exp": now + timedelta(minutes=expiry_minutes),
        "iat": now,
    }

    try:
        from jose import jwt as jose_jwt
        token = jose_jwt.encode(payload, jwt_secret, algorithm="HS256")
        logger.debug("[auth] JWT signed jwtSource=%s", jwt_source)
        return token, expiry_minutes * 60
    except Exception as exc:
        logger.error(
            "[auth] JWT encode failed jwtSource=%s reason=%s",
            jwt_source, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sign token",
        )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CustomerTokenRequest(BaseModel):
    # Primary field (new format from Commerce)
    tenantId: str = Field(..., description="Commerce tenant identifier (e.g. 'eukolakis')")
    host: str | None = Field(None, description="Requesting host for logging")
    lang: str | None = Field(None, description="Language hint")


class CustomerTokenResponse(BaseModel):
    token: str
    expiresIn: int


# ---------------------------------------------------------------------------
# Legacy login endpoint (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Customer token endpoint
# ---------------------------------------------------------------------------

@router.post("/customer-token", response_model=CustomerTokenResponse)
async def customer_token(
    body: CustomerTokenRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    x_thronos_commerce_key: str | None = Header(
        default=None, alias="X-Thronos-Commerce-Key"
    ),
) -> CustomerTokenResponse:
    tenant_id = body.tenantId.strip()
    req_host = (body.host or http_request.headers.get("host", "-")).strip()
    lang = body.lang or "el"

    # ── resolve secrets (log names only, never values) ───────────────────────
    expected_key, secret_source = _resolve_shared_secret()
    _, jwt_source = _resolve_jwt_secret()

    has_commerce_secret = bool(expected_key)
    has_jwt_secret = bool(jwt_source != "none")

    logger.info(
        "[auth] customer-token entered tenantId=%s host=%s lang=%s "
        "hasCommerceSecret=%s secretSource=%s hasJwtSecret=%s jwtSource=%s",
        tenant_id, req_host, lang,
        has_commerce_secret, secret_source,
        has_jwt_secret, jwt_source,
    )

    # ── shared-secret validation ──────────────────────────────────────────────
    if expected_key:
        incoming = (x_thronos_commerce_key or "").strip()
        if not incoming or incoming != expected_key:
            logger.warning(
                "[auth] customer-token REJECTED tenantId=%s host=%s "
                "reason=invalid_commerce_key secretSource=%s",
                tenant_id, req_host, secret_source,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-Thronos-Commerce-Key",
            )
    else:
        logger.warning(
            "[auth] customer-token key check SKIPPED — no secret configured "
            "(secretSource=none, dev mode)"
        )

    # ── shop lookup ───────────────────────────────────────────────────────────
    # asyncio.wait_for is intentionally avoided: cancelling a SQLAlchemy async
    # coroutine mid-flight leaves the session in a broken state, causing the
    # cleanup (rollback/close) to raise and drop the TCP connection.
    # DB-level timeouts (asyncpg command_timeout / statement_timeout) handle this instead.
    try:
        result = await db.execute(
            select(Shop).where(Shop.commerce_tenant_id == tenant_id)
        )
        shop = result.scalar_one_or_none()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[auth] customer-token DB ERROR tenantId=%s reason=%s",
            tenant_id, type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shop lookup failed — please retry",
        )

    if not shop:
        logger.warning(
            "[auth] customer-token NOT_FOUND tenantId=%s host=%s "
            "reason=no_shop_linked",
            tenant_id, req_host,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No VCA shop is linked to tenantId={tenant_id!r}. "
                "Run the seed script or link the shop in the VCA admin."
            ),
        )

    # ── sign JWT ──────────────────────────────────────────────────────────────
    customer_id = str(uuid.uuid4())
    expiry_minutes = int(getattr(settings, "jwt_expiration_minutes", 1440))

    token, expires_in = _sign_customer_jwt(
        customer_id=customer_id,
        tenant_id=tenant_id,
        shop_id=str(shop.id),
        expiry_minutes=expiry_minutes,
    )

    logger.info(
        "[auth] customer-token ISSUED tenantId=%s shop_id=%s expiresIn=%d",
        tenant_id, shop.id, expires_in,
    )
    return CustomerTokenResponse(token=token, expiresIn=expires_in)
