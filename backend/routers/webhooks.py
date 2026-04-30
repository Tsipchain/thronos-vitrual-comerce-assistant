"""
Webhook receiver: thronos-commerce → assistant.

Endpoint : POST /api/v1/webhooks/commerce
Security : HMAC-SHA256 in X-Thronos-Signature (sha256=<hex>).
           Key: COMMERCE_WEBHOOK_SECRET (shared with commerce).
           Requests without a valid signature are rejected with 401.
Supported: order.placed | order.status_changed | product.updated
"""
import asyncio
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from dependencies.database import get_db
from services import sync as sync_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

SUPPORTED_EVENTS = {"order.placed", "order.status_changed", "product.updated"}

# Sync ops budget: must finish before Railway’s 30-s reverse-proxy limit.
_SYNC_TIMEOUT = float(os.getenv("VCA_SYNC_TIMEOUT_S", "10"))


def _verify_signature(body: bytes, header_sig: str | None, secret: str) -> bool:
    """Return True iff the HMAC-SHA256 signature is valid. Never logs the secret."""
    if not secret:
        logger.error("[webhook] COMMERCE_WEBHOOK_SECRET not set — rejecting all requests")
        return False
    if not header_sig:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)


@router.post("/commerce")
async def receive_commerce_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_thronos_signature: str | None = Header(None, alias="X-Thronos-Signature"),
):
    """Receive and process events from thronos-commerce."""
    body = await request.body()

    secret = settings.commerce_webhook_secret or ""
    if not _verify_signature(body, x_thronos_signature, secret):
        logger.warning(
            "[webhook] path=POST /api/v1/webhooks/commerce reason=invalid_signature"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event     = str(payload.get("event")     or "").strip()
    tenant_id = str(payload.get("tenant_id") or "").strip()
    data      = payload.get("data") or {}

    if not event or not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: event, tenant_id",
        )

    if event not in SUPPORTED_EVENTS:
        logger.info(
            "[webhook] unsupported event=%s tenant=%s — acknowledged and ignored",
            event, tenant_id,
        )
        return {"status": "ignored", "event": event}

    logger.info("[webhook] received event=%s tenant=%s", event, tenant_id)

    try:
        if event == "order.placed":
            coro = sync_svc.sync_order_placed(db, tenant_id, data)
        elif event == "order.status_changed":
            coro = sync_svc.sync_order_status_changed(db, tenant_id, data)
        else:  # product.updated
            coro = sync_svc.sync_product_updated(db, tenant_id, data)

        ok = await asyncio.wait_for(coro, timeout=_SYNC_TIMEOUT)

        if ok:
            await db.commit()
        else:
            logger.warning(
                "[webhook] handler returned False event=%s tenant=%s", event, tenant_id
            )

    except asyncio.TimeoutError:
        await db.rollback()
        logger.error(
            "[webhook] sync timeout event=%s tenant=%s timeout_s=%.1f",
            event, tenant_id, _SYNC_TIMEOUT,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Sync operation timed out",
        )
    except Exception as exc:
        await db.rollback()
        logger.error(
            "[webhook] processing error event=%s tenant=%s reason=%s",
            event, tenant_id, type(exc).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing error",
        )

    return {"status": "ok", "event": event, "tenant_id": tenant_id}
