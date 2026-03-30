"""Commerce → Assistant sync service.

Handles incoming webhook events from thronos-commerce and keeps the
assistant DB up to date. All handlers are idempotent.
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.orders import Order, OrderItem
from models.products import Product
from models.shop import Shop

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

async def _shop_by_tenant(db: AsyncSession, tenant_id: str) -> Shop | None:
    result = await db.execute(
        select(Shop).where(Shop.commerce_tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


def _resolve_str(value) -> str:
    """Commerce stores names as {el: ..., en: ...} dicts or plain strings."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("el") or value.get("en") or str(value)
    return str(value)


# ── event handlers ────────────────────────────────────────────────────────────

async def sync_order_placed(db: AsyncSession, tenant_id: str, data: dict) -> bool:
    """Upsert an order from a commerce order.placed event."""
    shop = await _shop_by_tenant(db, tenant_id)
    if not shop:
        logger.warning("[sync] order.placed — no shop for tenant_id=%s", tenant_id)
        return False

    order_number = str(data.get("order_number") or data.get("orderId") or "").strip()
    if not order_number:
        logger.warning("[sync] order.placed — missing order_number in payload")
        return False

    # Idempotency: skip if already synced
    existing = await db.execute(
        select(Order).where(Order.shop_id == shop.id, Order.order_number == order_number)
    )
    if existing.scalar_one_or_none():
        logger.debug("[sync] order.placed — %s already exists, skipping", order_number)
        return True

    order = Order(
        shop_id=shop.id,
        customer_id=str(data.get("customer_id") or data.get("customerId") or "unknown"),
        order_number=order_number,
        status=data.get("status", "pending"),
        total_amount=float(data.get("total", 0)),
        shipping_cost=float(data.get("shipping_cost", 0)),
        currency=data.get("currency", "EUR"),
        shipping_method=data.get("shipping_method"),
        payment_method=data.get("payment_method"),
        payment_status=data.get("payment_status", "pending"),
        shipping_address=data.get("shipping_address"),
        notes=data.get("notes"),
    )
    db.add(order)
    await db.flush()

    for item in data.get("items", []):
        sku = str(item.get("sku") or item.get("productId") or "")
        product_id = "unknown"
        if sku:
            pr = await db.execute(
                select(Product).where(Product.shop_id == shop.id, Product.sku == sku)
            )
            p = pr.scalar_one_or_none()
            if p:
                product_id = p.id

        db.add(OrderItem(
            order_id=order.id,
            product_id=product_id,
            sku=sku,
            product_name=_resolve_str(item.get("name", sku)),
            quantity=int(item.get("quantity", 1)),
            unit_price=float(item.get("unit_price", 0)),
            total_price=float(item.get("total_price", 0)),
        ))

    logger.info("[sync] order.placed — %s synced for shop %s", order_number, shop.id)
    return True


async def sync_order_status_changed(db: AsyncSession, tenant_id: str, data: dict) -> bool:
    """Update order status from a commerce order.status_changed event."""
    shop = await _shop_by_tenant(db, tenant_id)
    if not shop:
        return False

    order_number = str(data.get("order_number") or data.get("orderId") or "").strip()
    if not order_number:
        return False

    result = await db.execute(
        select(Order).where(Order.shop_id == shop.id, Order.order_number == order_number)
    )
    order = result.scalar_one_or_none()
    if not order:
        # Never seen this order — treat as full placement
        logger.info("[sync] order.status_changed — %s unknown, falling back to order.placed", order_number)
        return await sync_order_placed(db, tenant_id, data)

    new_status = str(data.get("status") or data.get("newStatus") or "").strip()
    if new_status:
        order.status = new_status
        now = datetime.utcnow()
        if new_status == "confirmed" and not order.confirmed_at:
            order.confirmed_at = now
        elif new_status == "shipped" and not order.shipped_at:
            order.shipped_at = now
        elif new_status == "delivered" and not order.delivered_at:
            order.delivered_at = now
        elif new_status == "cancelled" and not order.cancelled_at:
            order.cancelled_at = now

    if data.get("tracking_number"):
        order.tracking_number = str(data["tracking_number"])

    logger.info("[sync] order.status_changed — %s → %s", order_number, new_status)
    return True


async def sync_product_updated(db: AsyncSession, tenant_id: str, data: dict) -> bool:
    """Upsert a product from a commerce product.updated event."""
    shop = await _shop_by_tenant(db, tenant_id)
    if not shop:
        return False

    sku = str(data.get("sku") or data.get("id") or data.get("productId") or "").strip()
    if not sku:
        logger.warning("[sync] product.updated — missing sku in payload")
        return False

    result = await db.execute(
        select(Product).where(Product.shop_id == shop.id, Product.sku == sku)
    )
    product = result.scalar_one_or_none()

    if product:
        if "stock" in data:
            product.stock_quantity = int(data["stock"])
        if "price" in data:
            product.price = float(data["price"])
        if "name" in data:
            product.name = _resolve_str(data["name"])
        if "description" in data:
            product.description = _resolve_str(data["description"])
        product.is_active = bool(data.get("active", product.is_active))
        logger.info("[sync] product.updated — %s updated for shop %s", sku, shop.id)
    else:
        product = Product(
            shop_id=shop.id,
            sku=sku,
            name=_resolve_str(data.get("name", sku)),
            description=_resolve_str(data.get("description", "")),
            category=str(data.get("categoryId") or data.get("category", "")),
            price=float(data.get("price", 0)),
            stock_quantity=int(data.get("stock", 0)),
            low_stock_threshold=int(data.get("low_stock_threshold", 5)),
            images=[data["imageUrl"]] if data.get("imageUrl") else [],
            is_active=bool(data.get("active", True)),
        )
        db.add(product)
        logger.info("[sync] product.updated — %s created for shop %s", sku, shop.id)

    return True
