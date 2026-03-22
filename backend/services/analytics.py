import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customer
from models.orders import Order, OrderItem
from models.products import Product
from models.returns import ReturnRequest
from models.vouchers import Voucher

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def revenue_summary(self, shop_id: str, days: int = 30) -> dict:
        since = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(
                func.count().label("total_orders"),
                func.sum(Order.total_amount).label("total_revenue"),
                func.avg(Order.total_amount).label("avg_order_value"),
            ).where(
                and_(Order.shop_id == shop_id, Order.created_at >= since,
                     Order.status.notin_(["cancelled"]))
            )
        )
        row = result.one()
        # Refunds
        refund_result = await self.db.execute(
            select(func.sum(ReturnRequest.refund_amount)).where(
                and_(ReturnRequest.shop_id == shop_id, ReturnRequest.status == "completed",
                     ReturnRequest.created_at >= since)
            )
        )
        total_refunds = refund_result.scalar() or 0

        return {
            "period_days": days,
            "total_orders": row.total_orders or 0,
            "total_revenue": round(row.total_revenue or 0, 2),
            "avg_order_value": round(row.avg_order_value or 0, 2),
            "total_refunds": round(total_refunds, 2),
            "net_revenue": round((row.total_revenue or 0) - total_refunds, 2),
        }

    async def top_cancelled_skus(self, shop_id: str, limit: int = 10) -> list[dict]:
        cancelled_orders = select(Order.id).where(
            and_(Order.shop_id == shop_id, Order.status == "cancelled")
        ).subquery()
        result = await self.db.execute(
            select(
                OrderItem.sku,
                OrderItem.product_name,
                func.sum(OrderItem.quantity).label("cancelled_qty"),
                func.count().label("cancel_count"),
            ).where(OrderItem.order_id.in_(select(cancelled_orders.c.id)))
            .group_by(OrderItem.sku, OrderItem.product_name)
            .order_by(desc("cancelled_qty"))
            .limit(limit)
        )
        return [
            {"sku": r.sku, "product_name": r.product_name,
             "cancelled_quantity": r.cancelled_qty, "cancellation_count": r.cancel_count}
            for r in result.all()
        ]

    async def customer_risk_report(self, shop_id: str) -> list[dict]:
        result = await self.db.execute(
            select(Customer).where(
                and_(Customer.shop_id == shop_id, Customer.risk_score > 0.3)
            ).order_by(Customer.risk_score.desc()).limit(20)
        )
        customers = result.scalars().all()
        return [
            {
                "id": c.id, "name": c.name, "email": c.email,
                "risk_score": c.risk_score,
                "total_orders": c.total_orders, "total_returns": c.total_returns,
                "return_rate": round(c.total_returns / max(c.total_orders, 1) * 100, 1),
                "total_spent": round(c.total_spent, 2),
                "total_refunded": round(c.total_refunded, 2),
            }
            for c in customers
        ]

    async def orders_by_status(self, shop_id: str) -> dict:
        result = await self.db.execute(
            select(Order.status, func.count().label("count")).where(
                Order.shop_id == shop_id
            ).group_by(Order.status)
        )
        return {row.status: row.count for row in result.all()}

    async def top_selling_products(self, shop_id: str, days: int = 30, limit: int = 10) -> list[dict]:
        since = datetime.utcnow() - timedelta(days=days)
        valid_orders = select(Order.id).where(
            and_(Order.shop_id == shop_id, Order.created_at >= since,
                 Order.status.notin_(["cancelled"]))
        ).subquery()
        result = await self.db.execute(
            select(
                OrderItem.product_id, OrderItem.product_name, OrderItem.sku,
                func.sum(OrderItem.quantity).label("total_sold"),
                func.sum(OrderItem.total_price).label("total_revenue"),
            ).where(OrderItem.order_id.in_(select(valid_orders.c.id)))
            .group_by(OrderItem.product_id, OrderItem.product_name, OrderItem.sku)
            .order_by(desc("total_sold"))
            .limit(limit)
        )
        return [
            {"product_id": r.product_id, "name": r.product_name, "sku": r.sku,
             "total_sold": r.total_sold, "total_revenue": round(r.total_revenue or 0, 2)}
            for r in result.all()
        ]
