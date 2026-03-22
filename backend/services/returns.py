import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.customers import Customer
from models.orders import Order
from models.returns import ReturnRequest

logger = logging.getLogger(__name__)


class ReturnsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_return_request(
        self, shop_id: str, order_id: str, customer_id: str, reason: str,
        reason_category: str | None = None, items: list | None = None,
        refund_type: str | None = None,
    ) -> ReturnRequest:
        # Verify order exists
        order_result = await self.db.execute(
            select(Order).where(and_(Order.id == order_id, Order.shop_id == shop_id))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("Order not found")
        if order.status not in ("delivered", "shipped"):
            raise ValueError(f"Cannot return order in status '{order.status}'")

        # Evaluate risk
        risk_score = await self._calculate_risk_score(customer_id, shop_id)
        ai_recommendation = self._generate_recommendation(risk_score, reason_category)

        ret = ReturnRequest(
            shop_id=shop_id,
            order_id=order_id,
            customer_id=customer_id,
            reason=reason,
            reason_category=reason_category,
            items=items or [],
            refund_type=refund_type or "voucher",
            refund_amount=order.total_amount,
            currency=order.currency,
            risk_score=risk_score,
            ai_recommendation=ai_recommendation,
        )
        self.db.add(ret)
        await self.db.commit()
        await self.db.refresh(ret)
        logger.info(f"Return request created: {ret.id} for order {order_id}, risk={risk_score:.2f}")
        return ret

    async def _calculate_risk_score(self, customer_id: str, shop_id: str) -> float:
        score = 0.0
        # Check recent returns
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        recent_returns = await self.db.execute(
            select(func.count()).select_from(ReturnRequest).where(
                and_(
                    ReturnRequest.customer_id == customer_id,
                    ReturnRequest.shop_id == shop_id,
                    ReturnRequest.created_at >= thirty_days_ago,
                )
            )
        )
        count = recent_returns.scalar() or 0
        if count >= 5:
            score += 0.5
        elif count >= 3:
            score += 0.3
        elif count >= 2:
            score += 0.1

        # Check return-to-order ratio
        customer_result = await self.db.execute(
            select(Customer).where(and_(Customer.id == customer_id, Customer.shop_id == shop_id))
        )
        customer = customer_result.scalar_one_or_none()
        if customer and customer.total_orders > 0:
            ratio = customer.total_returns / customer.total_orders
            if ratio > 0.5:
                score += 0.3
            elif ratio > 0.3:
                score += 0.15

        return min(score, 1.0)

    def _generate_recommendation(self, risk_score: float, reason_category: str | None) -> str:
        if risk_score >= 0.6:
            return "HIGH RISK - Manual review recommended. Customer has a pattern of frequent returns."
        if risk_score >= 0.3:
            return "MEDIUM RISK - Review before approval. Consider offering voucher instead of refund."
        if reason_category in ("defective", "wrong_item"):
            return "AUTO-APPROVE recommended. Product issue - customer not at fault."
        return "LOW RISK - Safe to approve. Normal return pattern."

    async def approve_return(self, return_id: str, shop_id: str, refund_type: str | None = None,
                              refund_amount: float | None = None, admin_notes: str | None = None) -> ReturnRequest:
        result = await self.db.execute(
            select(ReturnRequest).where(and_(ReturnRequest.id == return_id, ReturnRequest.shop_id == shop_id))
        )
        ret = result.scalar_one_or_none()
        if not ret:
            raise ValueError("Return request not found")
        ret.status = "approved"
        ret.approved_at = datetime.utcnow()
        if refund_type:
            ret.refund_type = refund_type
        if refund_amount is not None:
            ret.refund_amount = refund_amount
        if admin_notes:
            ret.admin_notes = admin_notes
        await self.db.commit()
        await self.db.refresh(ret)
        return ret

    async def reject_return(self, return_id: str, shop_id: str, reason: str) -> ReturnRequest:
        result = await self.db.execute(
            select(ReturnRequest).where(and_(ReturnRequest.id == return_id, ReturnRequest.shop_id == shop_id))
        )
        ret = result.scalar_one_or_none()
        if not ret:
            raise ValueError("Return request not found")
        ret.status = "rejected"
        ret.rejected_at = datetime.utcnow()
        ret.rejected_reason = reason
        await self.db.commit()
        await self.db.refresh(ret)
        return ret

    async def detect_suspicious_patterns(self, shop_id: str) -> list[dict]:
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        result = await self.db.execute(
            select(
                ReturnRequest.customer_id,
                func.count().label("return_count"),
                func.sum(ReturnRequest.refund_amount).label("total_refunded"),
            ).where(
                and_(ReturnRequest.shop_id == shop_id, ReturnRequest.created_at >= thirty_days_ago)
            ).group_by(ReturnRequest.customer_id)
            .having(func.count() >= 3)
            .order_by(func.count().desc())
        )
        rows = result.all()
        suspicious = []
        for row in rows:
            customer_result = await self.db.execute(
                select(Customer).where(Customer.id == row.customer_id)
            )
            customer = customer_result.scalar_one_or_none()
            suspicious.append({
                "customer_id": row.customer_id,
                "customer_name": customer.name if customer else "Unknown",
                "customer_email": customer.email if customer else "Unknown",
                "returns_last_30_days": row.return_count,
                "total_refunded": round(row.total_refunded or 0, 2),
                "risk_level": "high" if row.return_count >= 5 else "medium",
            })
        return suspicious

    async def get_returns_summary(self, shop_id: str, days: int = 7) -> dict:
        since = datetime.utcnow() - timedelta(days=days)
        result = await self.db.execute(
            select(
                ReturnRequest.status,
                func.count().label("count"),
                func.sum(ReturnRequest.refund_amount).label("total"),
            ).where(
                and_(ReturnRequest.shop_id == shop_id, ReturnRequest.created_at >= since)
            ).group_by(ReturnRequest.status)
        )
        rows = result.all()
        summary = {"period_days": days, "statuses": {}}
        total_count = 0
        total_amount = 0.0
        for row in rows:
            summary["statuses"][row.status] = {"count": row.count, "total_amount": round(row.total or 0, 2)}
            total_count += row.count
            total_amount += row.total or 0
        summary["total_returns"] = total_count
        summary["total_refund_amount"] = round(total_amount, 2)
        return summary
