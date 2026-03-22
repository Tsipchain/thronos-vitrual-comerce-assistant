import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.notifications import Notification

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _create_notification(
        self, shop_id: str, notif_type: str, recipient: str,
        subject: str | None, body: str, triggered_by: str | None = None,
        reference_id: str | None = None, reference_type: str | None = None,
    ) -> Notification:
        notif = Notification(
            shop_id=shop_id, type=notif_type, recipient=recipient,
            subject=subject, body=body, status="pending",
            triggered_by=triggered_by, reference_id=reference_id,
            reference_type=reference_type,
        )
        self.db.add(notif)
        await self.db.commit()
        await self.db.refresh(notif)
        return notif

    async def send_email(self, shop_id: str, recipient: str, subject: str, body: str,
                          triggered_by: str | None = None, reference_id: str | None = None) -> Notification:
        notif = await self._create_notification(
            shop_id, "email", recipient, subject, body, triggered_by, reference_id, "email"
        )
        # In production: integrate with SMTP / SendGrid / SES
        try:
            logger.info(f"[EMAIL] To: {recipient}, Subject: {subject}")
            notif.status = "sent"
        except Exception as e:
            logger.error(f"Email failed: {e}")
            notif.status = "failed"
            notif.error_message = str(e)
        await self.db.commit()
        return notif

    async def send_sms(self, shop_id: str, phone: str, message: str,
                        triggered_by: str | None = None, reference_id: str | None = None) -> Notification:
        notif = await self._create_notification(
            shop_id, "sms", phone, None, message, triggered_by, reference_id, "sms"
        )
        try:
            logger.info(f"[SMS] To: {phone}, Body: {message[:50]}...")
            notif.status = "sent"
        except Exception as e:
            logger.error(f"SMS failed: {e}")
            notif.status = "failed"
            notif.error_message = str(e)
        await self.db.commit()
        return notif

    async def send_push(self, shop_id: str, user_id: str, title: str, body: str,
                         triggered_by: str | None = None, reference_id: str | None = None) -> Notification:
        notif = await self._create_notification(
            shop_id, "push", user_id, title, body, triggered_by, reference_id, "push"
        )
        try:
            logger.info(f"[PUSH] To: {user_id}, Title: {title}")
            notif.status = "sent"
        except Exception as e:
            logger.error(f"Push failed: {e}")
            notif.status = "failed"
            notif.error_message = str(e)
        await self.db.commit()
        return notif

    async def notify_low_stock(self, shop_id: str, merchant_email: str, products: list[dict]) -> Notification:
        product_lines = "\n".join(
            f"- {p['name']} (SKU: {p['sku']}): {p['stock_quantity']} left (threshold: {p['low_stock_threshold']})"
            for p in products
        )
        return await self.send_email(
            shop_id, merchant_email,
            f"⚠️ Low Stock Alert - {len(products)} product(s)",
            f"The following products are running low:\n\n{product_lines}\n\nPlease restock soon.",
            triggered_by="low_stock",
        )

    async def notify_return_opened(self, shop_id: str, merchant_email: str, return_data: dict) -> Notification:
        return await self.send_email(
            shop_id, merchant_email,
            f"📦 New Return Request - Order #{return_data.get('order_number', 'N/A')}",
            f"A new return request has been submitted.\n\n"
            f"Reason: {return_data.get('reason', 'N/A')}\n"
            f"Risk Score: {return_data.get('risk_score', 0):.2f}\n"
            f"AI Recommendation: {return_data.get('ai_recommendation', 'N/A')}",
            triggered_by="return_opened",
            reference_id=return_data.get("id"),
        )

    async def notify_voucher_approved(self, shop_id: str, customer_email: str, voucher_data: dict) -> Notification:
        return await self.send_email(
            shop_id, customer_email,
            f"🎁 Your voucher is ready! Code: {voucher_data.get('code', '')}",
            f"You have received a {voucher_data.get('type', '')} voucher!\n\n"
            f"Code: {voucher_data.get('code', '')}\n"
            f"Value: {voucher_data.get('value', 0)} {voucher_data.get('currency', 'EUR')}\n"
            f"Use it on your next order.",
            triggered_by="voucher_created",
            reference_id=voucher_data.get("id"),
        )

    async def notify_suspicious_activity(self, shop_id: str, merchant_email: str, patterns: list[dict]) -> Notification:
        lines = "\n".join(
            f"- {p['customer_name']} ({p['customer_email']}): "
            f"{p['returns_last_30_days']} returns, €{p['total_refunded']:.2f} refunded"
            for p in patterns
        )
        return await self.send_email(
            shop_id, merchant_email,
            f"🚨 Suspicious Return Patterns Detected",
            f"The following customers have unusual return activity:\n\n{lines}",
            triggered_by="suspicious_pattern",
        )

    async def notify_stuck_order(self, shop_id: str, merchant_email: str, order_data: dict) -> Notification:
        return await self.send_email(
            shop_id, merchant_email,
            f"⏰ Stuck Order Alert - #{order_data.get('order_number', 'N/A')}",
            f"Order #{order_data.get('order_number')} has been in '{order_data.get('status')}' "
            f"status for over {order_data.get('hours_stuck', '?')} hours.",
            triggered_by="stuck_order",
            reference_id=order_data.get("id"),
        )
