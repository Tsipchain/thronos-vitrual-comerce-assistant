import logging
from datetime import datetime

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.vouchers import Voucher, generate_voucher_code

logger = logging.getLogger(__name__)


class VoucherService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_voucher(
        self, shop_id: str, voucher_type: str, value: float,
        customer_id: str | None = None, created_by: str = "manual",
        return_request_id: str | None = None, **kwargs
    ) -> Voucher:
        voucher = Voucher(
            shop_id=shop_id,
            customer_id=customer_id,
            code=generate_voucher_code(),
            type=voucher_type,
            value=value,
            currency=kwargs.get("currency", "EUR"),
            min_order_amount=kwargs.get("min_order_amount", 0.0),
            max_discount_amount=kwargs.get("max_discount_amount"),
            applicable_categories=kwargs.get("applicable_categories", []),
            applicable_products=kwargs.get("applicable_products", []),
            max_uses=kwargs.get("max_uses", 1),
            max_uses_per_customer=kwargs.get("max_uses_per_customer", 1),
            valid_from=kwargs.get("valid_from"),
            valid_until=kwargs.get("valid_until"),
            created_by=created_by,
            return_request_id=return_request_id,
        )
        self.db.add(voucher)
        await self.db.commit()
        await self.db.refresh(voucher)
        logger.info(f"Voucher created: {voucher.code} type={voucher_type} value={value} for shop {shop_id}")
        return voucher

    async def validate_voucher(self, code: str, order_amount: float, customer_id: str | None = None) -> dict:
        result = await self.db.execute(select(Voucher).where(Voucher.code == code))
        voucher = result.scalar_one_or_none()
        if not voucher:
            return {"valid": False, "discount_amount": 0, "message": "Voucher code not found"}
        if not voucher.is_active:
            return {"valid": False, "discount_amount": 0, "message": "Voucher is inactive"}
        if voucher.is_fully_used:
            return {"valid": False, "discount_amount": 0, "message": "Voucher has been fully used"}
        now = datetime.utcnow()
        if voucher.valid_from and now < voucher.valid_from:
            return {"valid": False, "discount_amount": 0, "message": "Voucher is not yet active"}
        if voucher.valid_until and now > voucher.valid_until:
            return {"valid": False, "discount_amount": 0, "message": "Voucher has expired"}
        if order_amount < voucher.min_order_amount:
            return {"valid": False, "discount_amount": 0,
                    "message": f"Minimum order amount is {voucher.min_order_amount} {voucher.currency}"}
        if voucher.customer_id and customer_id and voucher.customer_id != customer_id:
            return {"valid": False, "discount_amount": 0, "message": "Voucher is not valid for this customer"}

        # Calculate discount
        if voucher.type == "percentage":
            discount = order_amount * (voucher.value / 100)
            if voucher.max_discount_amount:
                discount = min(discount, voucher.max_discount_amount)
        elif voucher.type == "free_shipping":
            discount = 0  # handled at checkout
        else:  # fixed, credit_note
            discount = min(voucher.value, order_amount)

        return {"valid": True, "discount_amount": round(discount, 2),
                "message": f"Voucher applied! Discount: {discount:.2f} {voucher.currency}"}

    async def create_credit_note(self, shop_id: str, return_request_id: str,
                                  customer_id: str, amount: float) -> Voucher:
        return await self.generate_voucher(
            shop_id=shop_id, voucher_type="credit_note", value=amount,
            customer_id=customer_id, created_by="return",
            return_request_id=return_request_id,
        )

    async def get_voucher_stats(self, shop_id: str) -> dict:
        result = await self.db.execute(
            select(
                Voucher.type,
                Voucher.created_by,
                func.count().label("count"),
                func.sum(Voucher.value).label("total_value"),
                func.sum(Voucher.current_uses).label("total_uses"),
            ).where(Voucher.shop_id == shop_id)
            .group_by(Voucher.type, Voucher.created_by)
        )
        rows = result.all()
        stats = {"by_type": {}, "by_source": {}, "total_vouchers": 0, "total_value": 0}
        for row in rows:
            stats["by_type"].setdefault(row.type, {"count": 0, "value": 0})
            stats["by_type"][row.type]["count"] += row.count
            stats["by_type"][row.type]["value"] += round(row.total_value or 0, 2)
            stats["by_source"].setdefault(row.created_by, {"count": 0})
            stats["by_source"][row.created_by]["count"] += row.count
            stats["total_vouchers"] += row.count
            stats["total_value"] += row.total_value or 0
        stats["total_value"] = round(stats["total_value"], 2)
        return stats
