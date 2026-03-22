import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_shop_id
from dependencies.database import get_db
from models.orders import Order, OrderItem
from models.products import Product
from schemas.orders import OrderCreate, OrderResponse, OrderStatusUpdate, OrderListResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("/", response_model=OrderListResponse)
async def list_orders(
    status: str | None = None,
    customer_id: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(Order).where(Order.shop_id == shop_id)
    if status:
        query = query.where(Order.status == status)
    if customer_id:
        query = query.where(Order.customer_id == customer_id)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar() or 0

    query = query.order_by(Order.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().all()
    return OrderListResponse(orders=orders, total=total, page=page, per_page=per_page)


@router.post("/", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    total = 0.0
    order = Order(
        shop_id=shop_id,
        customer_id=data.customer_id,
        order_number=order_number,
        shipping_method=data.shipping_method,
        shipping_address=data.shipping_address,
        billing_address=data.billing_address,
        payment_method=data.payment_method,
        voucher_code=data.voucher_code,
        notes=data.notes,
    )
    db.add(order)
    await db.flush()

    for item_data in data.items:
        prod_result = await db.execute(
            select(Product).where(and_(Product.id == item_data.product_id, Product.shop_id == shop_id))
        )
        product = prod_result.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=400, detail=f"Product {item_data.product_id} not found")
        if product.available_stock < item_data.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product.name}")

        item_total = product.price * item_data.quantity
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            sku=product.sku,
            product_name=product.name,
            quantity=item_data.quantity,
            unit_price=product.price,
            total_price=item_total,
        )
        db.add(item)
        total += item_total
        product.reserved_quantity += item_data.quantity

    order.total_amount = total
    await db.commit()
    await db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(and_(Order.id == order_id, Order.shop_id == shop_id))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    data: OrderStatusUpdate,
    shop_id: str = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).where(and_(Order.id == order_id, Order.shop_id == shop_id))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    valid_transitions = {
        "pending": ["confirmed", "cancelled"],
        "confirmed": ["processing", "cancelled"],
        "processing": ["shipped", "cancelled"],
        "shipped": ["delivered"],
        "delivered": [],
        "cancelled": [],
    }
    if data.status not in valid_transitions.get(order.status, []):
        raise HTTPException(status_code=400,
                            detail=f"Cannot transition from '{order.status}' to '{data.status}'")

    order.status = data.status
    if data.tracking_number:
        order.tracking_number = data.tracking_number
    if data.internal_notes:
        order.internal_notes = data.internal_notes

    now = datetime.utcnow()
    if data.status == "confirmed":
        order.confirmed_at = now
    elif data.status == "shipped":
        order.shipped_at = now
    elif data.status == "delivered":
        order.delivered_at = now
        # Update product stats
        items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
        for item in items_result.scalars().all():
            prod_result = await db.execute(select(Product).where(Product.id == item.product_id))
            product = prod_result.scalar_one_or_none()
            if product:
                product.stock_quantity -= item.quantity
                product.reserved_quantity = max(0, product.reserved_quantity - item.quantity)
                product.total_sold += item.quantity
                product.last_sold_at = now
    elif data.status == "cancelled":
        order.cancelled_at = now
        items_result = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
        for item in items_result.scalars().all():
            prod_result = await db.execute(select(Product).where(Product.id == item.product_id))
            product = prod_result.scalar_one_or_none()
            if product:
                product.reserved_quantity = max(0, product.reserved_quantity - item.quantity)

    await db.commit()
    await db.refresh(order)
    return order
