"""Webhook receiver: thronos-commerce → assistant.

Endpoint: POST /api/v1/webhooks/commerce

Security: HMAC-SHA256 signature in X-Thronos-Signature header.
  Format: sha256=<hex digest>
  Key:    COMMERCE_WEBHOOK_SECRET env var (both sides must share the same value)
  If the secret is not configured, all webhook requests are rejected with 401.

Supported events:
  order.placed          → upsert order + items
  order.status_changed  → update order status / tracking
  product.updated       → upsert product
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from dependencies.database import get_db
from services import sync as sync_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

SUPPORTED_EVENTS = {"order.placed", "order.status_changed", "product.updated"}


def _verify_signature(body: bytes, header_sig: str | None, secret: str) -> bool:
    """Return True if the request signature is valid."""
    # SECURITY: Webhook secret now required — Phase 0 hardening
    if not secret:
        logger.error("[webhook] COMMERCE_WEBHOOK_SECRET not set — rejecting request")
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
        logger.warning("[webhook] Invalid signature — rejected")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = str(payload.get("event") or "").strip()
    tenant_id = str(payload.get("tenant_id") or "").strip()
    data = payload.get("data") or {}

    if not event or not tenant_id:
        raise HTTPException(status_code=400, detail="Missing required fields: event, tenant_id")

    if event not in SUPPORTED_EVENTS:
        logger.info("[webhook] Unsupported event '%s' — acknowledged and ignored", event)
        return {"status": "ignored", "event": event}

    logger.info("[webhook] Received %s for tenant=%s", event, tenant_id)

    try:
        if event == "order.placed":
            ok = await sync_svc.sync_order_placed(db, tenant_id, data)
        elif event == "order.status_changed":
            ok = await sync_svc.sync_order_status_changed(db, tenant_id, data)
        elif event == "product.updated":
            ok = await sync_svc.sync_product_updated(db, tenant_id, data)
        else:
            ok = False

        if ok:
            await db.commit()
        else:
            logger.warning("[webhook] Handler returned False for %s / tenant=%s", event, tenant_id)

    except Exception as exc:
        await db.rollback()
        logger.error("[webhook] Error processing %s: %s", event, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Webhook processing error")

    return {"status": "ok", "event": event, "tenant_id": tenant_id}
