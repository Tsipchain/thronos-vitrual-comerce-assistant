import logging
import secrets

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.orders import Order, OrderItem
from models.products import Product
from models.shipping import ShippingLabel

logger = logging.getLogger(__name__)


class ShippingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_shipping_label(
        self, shop_id: str, order_id: str, carrier: str,
        sender_address: dict | None = None, recipient_address: dict | None = None,
        weight_kg: float | None = None, dimensions: dict | None = None,
        packing_instructions: str | None = None,
    ) -> ShippingLabel:
        # Verify order
        order_result = await self.db.execute(
            select(Order).where(and_(Order.id == order_id, Order.shop_id == shop_id))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("Order not found")

        tracking = self._generate_tracking_number(carrier)
        label = ShippingLabel(
            shop_id=shop_id,
            order_id=order_id,
            carrier=carrier,
            tracking_number=tracking,
            label_type="shipping",
            status="created",
            sender_address=sender_address,
            recipient_address=recipient_address or order.shipping_address,
            weight_kg=weight_kg,
            dimensions=dimensions,
            packing_instructions=packing_instructions,
        )
        self.db.add(label)

        # Update order with tracking
        order.tracking_number = tracking
        await self.db.commit()
        await self.db.refresh(label)
        logger.info(f"Shipping label created: {label.id}, tracking={tracking}")
        return label

    async def create_return_label(
        self, shop_id: str, return_request_id: str, order_id: str, carrier: str,
        customer_address: dict | None = None, warehouse_address: dict | None = None,
    ) -> ShippingLabel:
        tracking = self._generate_tracking_number(carrier)
        label = ShippingLabel(
            shop_id=shop_id,
            order_id=order_id,
            return_request_id=return_request_id,
            carrier=carrier,
            tracking_number=tracking,
            label_type="return",
            status="created",
            sender_address=customer_address,
            recipient_address=warehouse_address,
        )
        self.db.add(label)
        await self.db.commit()
        await self.db.refresh(label)
        return label

    async def generate_packing_instructions(self, order_id: str, shop_id: str) -> dict:
        order_result = await self.db.execute(
            select(Order).where(and_(Order.id == order_id, Order.shop_id == shop_id))
        )
        order = order_result.scalar_one_or_none()
        if not order:
            raise ValueError("Order not found")

        items_result = await self.db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        items = items_result.scalars().all()

        packing_items = []
        total_weight = 0.0
        for item in items:
            prod_result = await self.db.execute(select(Product).where(Product.id == item.product_id))
            product = prod_result.scalar_one_or_none()
            packing_items.append({
                "sku": item.sku or (product.sku if product else "N/A"),
                "name": item.product_name,
                "quantity": item.quantity,
                "weight_kg": product.weight_kg if product else None,
                "fragile": "fragile" in (product.tags or []) if product else False,
            })
            if product and product.weight_kg:
                total_weight += product.weight_kg * item.quantity

        instructions_parts = [f"Order #{order.order_number} - Packing Instructions", "=" * 40]
        for pi in packing_items:
            line = f"- {pi['quantity']}x {pi['name']} (SKU: {pi['sku']})"
            if pi.get("fragile"):
                line += " ⚠️ FRAGILE - wrap with bubble wrap"
            instructions_parts.append(line)
        instructions_parts.append(f"\nEstimated total weight: {total_weight:.2f} kg")
        if any(pi.get("fragile") for pi in packing_items):
            instructions_parts.append("⚠️ Contains fragile items - use extra padding")

        return {
            "order_id": order_id,
            "order_number": order.order_number,
            "items": packing_items,
            "instructions": "\n".join(instructions_parts),
            "total_weight_kg": round(total_weight, 2),
            "shipping_address": order.shipping_address,
        }

    async def prepare_courier_summary(self, shop_id: str, order_ids: list[str]) -> list[dict]:
        summaries = {}
        for order_id in order_ids:
            labels_result = await self.db.execute(
                select(ShippingLabel).where(
                    and_(ShippingLabel.order_id == order_id, ShippingLabel.shop_id == shop_id,
                         ShippingLabel.label_type == "shipping")
                )
            )
            for label in labels_result.scalars().all():
                carrier = label.carrier
                summaries.setdefault(carrier, {"carrier": carrier, "total_shipments": 0, "labels": []})
                summaries[carrier]["total_shipments"] += 1
                summaries[carrier]["labels"].append({
                    "order_id": label.order_id,
                    "tracking": label.tracking_number,
                    "weight_kg": label.weight_kg,
                    "status": label.status,
                })
        return list(summaries.values())

    @staticmethod
    def _generate_tracking_number(carrier: str) -> str:
        prefix = {"acs": "ACS", "elta": "EL", "speedex": "SPX", "dhl": "DHL", "ups": "1Z",
                  "fedex": "FDX"}.get(carrier.lower(), "TH")
        return f"{prefix}{secrets.token_hex(6).upper()}"
