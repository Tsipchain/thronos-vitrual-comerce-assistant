import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.products import Product
from models.orders import OrderItem

logger = logging.getLogger(__name__)


class InventoryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_low_stock_products(self, shop_id: str) -> list[dict]:
        result = await self.db.execute(
            select(Product).where(
                and_(
                    Product.shop_id == shop_id,
                    Product.is_active == True,
                    Product.stock_quantity <= Product.low_stock_threshold,
                )
            ).order_by(Product.stock_quantity.asc())
        )
        products = result.scalars().all()
        return [
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "stock_quantity": p.stock_quantity,
                "low_stock_threshold": p.low_stock_threshold,
                "category": p.category,
            }
            for p in products
        ]

    async def get_dead_stock_products(self, shop_id: str, days: int = 90) -> list[dict]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(Product).where(
                and_(
                    Product.shop_id == shop_id,
                    Product.is_active == True,
                    Product.stock_quantity > 0,
                    (Product.last_sold_at == None) | (Product.last_sold_at < cutoff),
                )
            ).order_by(Product.last_sold_at.asc().nullsfirst())
        )
        products = result.scalars().all()
        return [
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "stock_quantity": p.stock_quantity,
                "last_sold_at": p.last_sold_at.isoformat() if p.last_sold_at else None,
                "days_since_sold": (datetime.utcnow() - p.last_sold_at).days if p.last_sold_at else "never",
                "value_stuck": p.stock_quantity * (p.cost_price or p.price),
            }
            for p in products
        ]

    async def suggest_restock(self, shop_id: str) -> list[dict]:
        result = await self.db.execute(
            select(Product).where(
                and_(
                    Product.shop_id == shop_id,
                    Product.is_active == True,
                    Product.stock_quantity <= Product.low_stock_threshold,
                    Product.total_sold > 0,
                )
            ).order_by(Product.total_sold.desc())
        )
        products = result.scalars().all()
        suggestions = []
        for p in products:
            avg_daily = p.total_sold / max(1, (datetime.utcnow() - p.created_at).days) if p.created_at else 0
            suggested_qty = max(int(avg_daily * 30), p.low_stock_threshold * 3)
            suggestions.append({
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "current_stock": p.stock_quantity,
                "avg_daily_sales": round(avg_daily, 2),
                "suggested_restock_qty": suggested_qty,
                "estimated_cost": round(suggested_qty * (p.cost_price or p.price), 2),
            })
        return suggestions

    async def update_stock(self, product_id: str, quantity: int, shop_id: str) -> dict:
        result = await self.db.execute(
            select(Product).where(and_(Product.id == product_id, Product.shop_id == shop_id))
        )
        product = result.scalar_one_or_none()
        if not product:
            raise ValueError(f"Product {product_id} not found")
        old_qty = product.stock_quantity
        product.stock_quantity = quantity
        await self.db.commit()
        await self.db.refresh(product)
        logger.info(f"Stock updated for {product.sku}: {old_qty} -> {quantity}")
        return {"id": product.id, "sku": product.sku, "old_stock": old_qty, "new_stock": quantity}

    async def check_stock_availability(self, product_id: str, quantity: int) -> dict:
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if not product:
            return {"available": False, "reason": "Product not found"}
        available = product.available_stock
        return {
            "available": available >= quantity,
            "product_id": product.id,
            "sku": product.sku,
            "requested": quantity,
            "in_stock": available,
            "shortage": max(0, quantity - available),
        }
