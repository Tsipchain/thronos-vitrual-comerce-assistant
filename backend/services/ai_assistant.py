"""
Thronos Commerce AI Assistant - The Brain
Processes natural language queries and routes to appropriate services.
Supports Greek and English.

Intent resolution order:
  1. ask_openai() — uses OPENAI_API_KEY if set; customer vs merchant system prompt
  2. Keyword handler fallback via INTENT_MAP + _handle_* methods
"""
import logging
import os
import re
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.orders import Order
from models.products import Product
from models.returns import ReturnRequest
from models.shop import Shop
from services.analytics import AnalyticsService
from services.inventory import InventoryService
from services.returns import ReturnsService
from services.vouchers import VoucherService

logger = logging.getLogger(__name__)

# Intent keywords in Greek and English
INTENT_MAP = {
    "order_status": [
        "order", "παραγγελία", "παραγγελια", "status", "κατάσταση", "κατασταση",
        "tracking", "where is", "πού είναι", "που ειναι", "track",
    ],
    "return_policy": [
        "return policy", "πολιτική επιστροφής", "πολιτικη επιστροφης",
        "can i return", "μπορώ να επιστρέψω", "μπορω να επιστρεψω",
        "return window", "days to return",
    ],
    "create_return": [
        "create return", "δημιουργία επιστροφής", "δημιουργια επιστροφης",
        "want to return", "θέλω να επιστρέψω", "θελω να επιστρεψω",
        "return request", "αίτημα επιστροφής",
    ],
    "check_stock": [
        "stock", "απόθεμα", "αποθεμα", "inventory", "available",
        "διαθέσιμο", "διαθεσιμο", "in stock", "έχετε", "εχετε",
    ],
    "low_stock": [
        "low stock", "χαμηλό stock", "χαμηλο stock", "χαμηλό απόθεμα",
        "running out", "τελειώνει", "τελειωνει", "ελάχιστο", "ελαχιστο",
    ],
    "dead_stock": [
        "dead stock", "νεκρό", "νεκρα", "δεν πουλάει", "δεν πουλαει",
        "sitting", "κάθονται", "καθονται", "unsold", "stale",
    ],
    "voucher": [
        "voucher", "κουπόνι", "κουπονι", "coupon", "discount",
        "έκπτωση", "εκπτωση", "credit note", "πιστωτικό",
    ],
    "shipping": [
        "shipping", "αποστολή", "αποστολη", "label", "ετικέτα", "ετικετα",
        "courier", "μεταφορικ", "packing", "συσκευασ",
    ],
    "revenue": [
        "revenue", "έσοδα", "εσοδα", "πόσα", "ποσα", "earnings",
        "sales", "πωλήσεις", "πωλησεις", "τζίρος", "τζιρος",
    ],
    "returns_summary": [
        "returns summary", "πόσες επιστροφές", "ποσες επιστροφες",
        "return stats", "επιστροφές αυτή", "επιστροφες αυτη",
    ],
    "suspicious": [
        "suspicious", "ύποπτο", "υποπτο", "fraud", "απάτη", "απατη",
        "pattern", "μοτίβο",
    ],
    "top_cancelled": [
        "cancelled", "ακυρώσεις", "ακυρωσεις", "most cancelled",
        "ακυρωμένα", "cancellation",
    ],
    "top_selling": [
        "top selling", "best seller", "δημοφιλ", "πιο πολύ πουλ",
        "top products", "κορυφαία", "κορυφαια",
    ],
    "restock": [
        "restock", "ανανέωση stock", "παραγγείλω", "παραγγειλω",
        "suggest restock", "τι να παραγγείλω",
    ],
    "help": [
        "help", "βοήθεια", "βοηθεια", "what can you do", "τι μπορείς",
        "τι μπορεις", "commands", "εντολές",
    ],
}


class CommerceAssistant:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.inventory = InventoryService(db)
        self.returns = ReturnsService(db)
        self.vouchers = VoucherService(db)
        self.analytics = AnalyticsService(db)

    async def _get_shop_context(self, shop_id: str) -> dict:
        """Fetch minimal shop context for AI system prompt."""
        try:
            result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
            shop = result.scalar_one_or_none()
            if not shop:
                return {}
            ctx = {
                "shop_name": shop.name,
                "return_window_days": shop.return_window_days,
            }
            # Include currency if the field exists on the model
            if hasattr(shop, "currency") and shop.currency:
                ctx["currency"] = shop.currency
            return ctx
        except Exception:
            return {}

    async def process_message(
        self,
        shop_id: str,
        message: str,
        context: dict | None = None,
        role: str = "customer",
    ) -> dict:
        msg_lower = message.lower().strip()
        intent = self._detect_intent(msg_lower)
        logger.info(f"[Assistant] shop={shop_id} role={role} intent={intent} msg={message[:80]}")

        # 1. Try Claude (Anthropic) first — highest quality
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if anthropic_key:
            try:
                from services.openai_brain import ask_claude
                shop_ctx = await self._get_shop_context(shop_id)
                anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
                result = await ask_claude(
                    message=message,
                    role=role,
                    shop_context=shop_ctx,
                    api_key=anthropic_key,
                    model=anthropic_model,
                )
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning(f"[Assistant] Claude failed, trying OpenAI: {exc}")

        # 2. Fall back to OpenAI if configured
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key:
            try:
                from services.openai_brain import ask_openai
                shop_ctx = await self._get_shop_context(shop_id)
                result = await ask_openai(
                    message=message,
                    role=role,
                    shop_context=shop_ctx,
                    api_key=openai_key,
                )
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning(f"[Assistant] OpenAI failed, falling back to keyword handlers: {exc}")

        # 3. Keyword handler fallback
        try:
            handler = getattr(self, f"_handle_{intent}", None)
            if handler:
                return await handler(shop_id, message, context)
            return self._help_response()
        except Exception as e:
            logger.error(f"Assistant error: {e}", exc_info=True)
            return {
                "response": f"Παρουσιάστηκε σφάλμα κατά την επεξεργασία. Παρακαλώ δοκιμάστε ξανά. ({e})",
                "data": None, "suggested_actions": [], "intent": intent,
            }

    def _detect_intent(self, message: str) -> str:
        best_intent = "help"
        best_score = 0
        for intent, keywords in INTENT_MAP.items():
            score = sum(1 for kw in keywords if kw in message)
            if score > best_score:
                best_score = score
                best_intent = intent
        return best_intent

    async def _handle_order_status(self, shop_id: str, message: str, context: dict | None) -> dict:
        order_num = self._extract_order_number(message)
        if context and context.get("order_id"):
            result = await self.db.execute(
                select(Order).where(and_(Order.id == context["order_id"], Order.shop_id == shop_id))
            )
        elif order_num:
            result = await self.db.execute(
                select(Order).where(and_(Order.order_number == order_num, Order.shop_id == shop_id))
            )
        else:
            return {
                "response": "Παρακαλώ δώστε μου τον αριθμό παραγγελίας. Π.χ. 'Κατάσταση παραγγελίας #12345'",
                "data": None,
                "suggested_actions": [{"label": "View all orders", "action": "list_orders", "params": {}}],
                "intent": "order_status",
            }

        order = result.scalar_one_or_none()
        if not order:
            return {"response": "Δεν βρέθηκε παραγγελία με αυτό τον αριθμό.", "data": None,
                    "suggested_actions": [], "intent": "order_status"}

        status_gr = {
            "pending": "Εκκρεμεί", "confirmed": "Επιβεβαιωμένη", "processing": "Σε επεξεργασία",
            "shipped": "Απεστάλη", "delivered": "Παραδόθηκε", "cancelled": "Ακυρωμένη",
        }
        return {
            "response": (
                f"Παραγγελία #{order.order_number}\n"
                f"Κατάσταση: {status_gr.get(order.status, order.status)}\n"
                f"Ποσό: {order.total_amount:.2f} {order.currency}\n"
                + (f"Tracking: {order.tracking_number}\n" if order.tracking_number else "")
                + f"Ημ/νία: {order.created_at.strftime('%d/%m/%Y %H:%M')}"
            ),
            "data": {
                "order_id": order.id, "order_number": order.order_number,
                "status": order.status, "total": order.total_amount,
                "tracking": order.tracking_number,
            },
            "suggested_actions": [
                {"label": "Create return", "action": "create_return", "params": {"order_id": order.id}},
                {"label": "View items", "action": "view_order_items", "params": {"order_id": order.id}},
            ],
            "intent": "order_status",
        }

    async def _handle_return_policy(self, shop_id: str, message: str, context: dict | None) -> dict:
        from models.shop import Shop
        result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()
        if not shop:
            return {"response": "Δεν βρέθηκε το κατάστημα.", "data": None, "suggested_actions": [], "intent": "return_policy"}
        policy = shop.return_policy_text or "Δεν έχει οριστεί πολιτική επιστροφών."
        return {
            "response": (
                f"Πολιτική Επιστροφών - {shop.name}\n\n"
                f"Παράθυρο επιστροφών: {shop.return_window_days} ημέρες\n\n"
                f"{policy}"
            ),
            "data": {"return_window_days": shop.return_window_days, "policy": policy},
            "suggested_actions": [
                {"label": "Create return", "action": "create_return", "params": {}},
            ],
            "intent": "return_policy",
        }

    async def _handle_create_return(self, shop_id: str, message: str, context: dict | None) -> dict:
        order_num = self._extract_order_number(message)
        if not order_num and not (context and context.get("order_id")):
            return {
                "response": "Για να δημιουργήσω αίτημα επιστροφής, χρειάζομαι τον αριθμό παραγγελίας.\nΠ.χ. 'Θέλω επιστροφή για #12345'",
                "data": None, "suggested_actions": [], "intent": "create_return",
            }
        return {
            "response": "Για να ολοκληρωθεί η επιστροφή, χρειάζομαι:\n1. Λόγος επιστροφής\n2. Ποια προϊόντα θέλετε να επιστρέψετε\n\nΠαρακαλώ χρησιμοποιήστε τη φόρμα επιστροφής.",
            "data": {"order_number": order_num},
            "suggested_actions": [
                {"label": "Open return form", "action": "open_return_form",
                 "params": {"order_number": order_num}},
            ],
            "intent": "create_return",
        }

    async def _handle_check_stock(self, shop_id: str, message: str, context: dict | None) -> dict:
        sku = self._extract_sku(message)
        if sku:
            result = await self.db.execute(
                select(Product).where(and_(Product.shop_id == shop_id, Product.sku == sku))
            )
            product = result.scalar_one_or_none()
            if product:
                return {
                    "response": f"Προϊόν: {product.name} (SKU: {product.sku})\nStock: {product.stock_quantity} τεμ.\nΔιαθέσιμο: {product.available_stock} τεμ.",
                    "data": {"sku": product.sku, "stock": product.stock_quantity, "available": product.available_stock},
                    "suggested_actions": [], "intent": "check_stock",
                }
        # General stock overview
        result = await self.db.execute(
            select(Product).where(and_(Product.shop_id == shop_id, Product.is_active == True))
            .order_by(Product.stock_quantity.asc()).limit(20)
        )
        products = result.scalars().all()
        lines = [f"- {p.name} (SKU: {p.sku}): {p.stock_quantity} τεμ." for p in products[:10]]
        return {
            "response": f"Απόθεμα (χαμηλότερα πρώτα):\n" + "\n".join(lines),
            "data": {"products": [{"sku": p.sku, "name": p.name, "stock": p.stock_quantity} for p in products]},
            "suggested_actions": [
                {"label": "Low stock alert", "action": "low_stock", "params": {}},
            ],
            "intent": "check_stock",
        }

    async def _handle_low_stock(self, shop_id: str, message: str, context: dict | None) -> dict:
        products = await self.inventory.get_low_stock_products(shop_id)
        if not products:
            return {"response": "Όλα τα προϊόντα έχουν επαρκές απόθεμα!", "data": {"products": []},
                    "suggested_actions": [], "intent": "low_stock"}
        lines = [f"- {p['name']} (SKU: {p['sku']}): {p['stock_quantity']} τεμ. (όριο: {p['low_stock_threshold']})" for p in products]
        return {
            "response": f"⚠️ {len(products)} προϊόντα με χαμηλό απόθεμα:\n" + "\n".join(lines),
            "data": {"products": products, "count": len(products)},
            "suggested_actions": [
                {"label": "Suggest restock", "action": "restock", "params": {}},
                {"label": "Export list", "action": "export_low_stock", "params": {}},
            ],
            "intent": "low_stock",
        }

    async def _handle_dead_stock(self, shop_id: str, message: str, context: dict | None) -> dict:
        products = await self.inventory.get_dead_stock_products(shop_id)
        if not products:
            return {"response": "Δεν υπάρχουν νεκρά προϊόντα! Όλα πουλάνε.", "data": {"products": []},
                    "suggested_actions": [], "intent": "dead_stock"}
        total_stuck = sum(p["value_stuck"] for p in products)
        lines = [f"- {p['name']} (SKU: {p['sku']}): {p['stock_quantity']} τεμ., τελευταία πώληση: {p['days_since_sold']}" for p in products[:10]]
        return {
            "response": (
                f"💀 {len(products)} νεκρά προϊόντα (>90 ημέρες χωρίς πώληση):\n"
                + "\n".join(lines)
                + f"\n\nΣυνολική αξία δεσμευμένη: €{total_stuck:.2f}"
            ),
            "data": {"products": products, "total_value_stuck": total_stuck},
            "suggested_actions": [
                {"label": "Create promotions", "action": "promote_dead_stock", "params": {}},
            ],
            "intent": "dead_stock",
        }

    async def _handle_voucher(self, shop_id: str, message: str, context: dict | None) -> dict:
        stats = await self.vouchers.get_voucher_stats(shop_id)
        return {
            "response": (
                f"Στατιστικά Vouchers:\n"
                f"Σύνολο: {stats['total_vouchers']} vouchers\n"
                f"Συνολική αξία: €{stats['total_value']:.2f}\n\n"
                + "\n".join(f"- {t}: {d['count']} ({d['value']:.2f}€)" for t, d in stats["by_type"].items())
            ),
            "data": stats,
            "suggested_actions": [
                {"label": "Create voucher", "action": "create_voucher", "params": {}},
            ],
            "intent": "voucher",
        }

    async def _handle_revenue(self, shop_id: str, message: str, context: dict | None) -> dict:
        days = 30
        if "εβδομάδα" in message or "week" in message:
            days = 7
        elif "σήμερα" in message or "today" in message:
            days = 1
        summary = await self.analytics.revenue_summary(shop_id, days)
        return {
            "response": (
                f"Έσοδα ({days} ημέρες):\n"
                f"Παραγγελίες: {summary['total_orders']}\n"
                f"Ακαθάριστα: €{summary['total_revenue']:.2f}\n"
                f"Μ.Ο. παραγγελίας: €{summary['avg_order_value']:.2f}\n"
                f"Επιστροφές: €{summary['total_refunds']:.2f}\n"
                f"Καθαρά: €{summary['net_revenue']:.2f}"
            ),
            "data": summary,
            "suggested_actions": [
                {"label": "Top products", "action": "top_selling", "params": {}},
            ],
            "intent": "revenue",
        }

    async def _handle_returns_summary(self, shop_id: str, message: str, context: dict | None) -> dict:
        days = 7
        if "μήνα" in message or "month" in message:
            days = 30
        summary = await self.returns.get_returns_summary(shop_id, days)
        status_lines = "\n".join(
            f"- {s}: {d['count']} (€{d['total_amount']:.2f})" for s, d in summary["statuses"].items()
        )
        return {
            "response": (
                f"Επιστροφές ({days} ημέρες):\n"
                f"Σύνολο: {summary['total_returns']}\n"
                f"Ποσό: €{summary['total_refund_amount']:.2f}\n\n"
                f"Ανά κατάσταση:\n{status_lines}"
            ),
            "data": summary,
            "suggested_actions": [
                {"label": "Suspicious patterns", "action": "suspicious", "params": {}},
            ],
            "intent": "returns_summary",
        }

    async def _handle_suspicious(self, shop_id: str, message: str, context: dict | None) -> dict:
        patterns = await self.returns.detect_suspicious_patterns(shop_id)
        if not patterns:
            return {"response": "Δεν εντοπίστηκαν ύποπτα μοτίβα επιστροφών.", "data": {"patterns": []},
                    "suggested_actions": [], "intent": "suspicious"}
        lines = [f"- {p['customer_name']} ({p['customer_email']}): {p['returns_last_30_days']} επιστροφές, €{p['total_refunded']:.2f}" for p in patterns]
        return {
            "response": f"🚨 Ύποπτα μοτίβα ({len(patterns)} πελάτες):\n" + "\n".join(lines),
            "data": {"patterns": patterns},
            "suggested_actions": [
                {"label": "Block customer", "action": "block_customer", "params": {}},
            ],
            "intent": "suspicious",
        }

    async def _handle_top_cancelled(self, shop_id: str, message: str, context: dict | None) -> dict:
        skus = await self.analytics.top_cancelled_skus(shop_id)
        if not skus:
            return {"response": "Δεν υπάρχουν ακυρώσεις!", "data": {"skus": []},
                    "suggested_actions": [], "intent": "top_cancelled"}
        lines = [f"- {s['product_name']} (SKU: {s['sku']}): {s['cancelled_quantity']} ακυρώσεις" for s in skus]
        return {
            "response": f"Κορυφαία SKU σε ακυρώσεις:\n" + "\n".join(lines),
            "data": {"skus": skus},
            "suggested_actions": [], "intent": "top_cancelled",
        }

    async def _handle_top_selling(self, shop_id: str, message: str, context: dict | None) -> dict:
        products = await self.analytics.top_selling_products(shop_id)
        if not products:
            return {"response": "Δεν υπάρχουν πωλήσεις ακόμα.", "data": {"products": []},
                    "suggested_actions": [], "intent": "top_selling"}
        lines = [f"- {p['name']} (SKU: {p['sku']}): {p['total_sold']} τεμ., €{p['total_revenue']:.2f}" for p in products]
        return {
            "response": f"Top Selling (30 ημέρες):\n" + "\n".join(lines),
            "data": {"products": products},
            "suggested_actions": [], "intent": "top_selling",
        }

    async def _handle_restock(self, shop_id: str, message: str, context: dict | None) -> dict:
        suggestions = await self.inventory.suggest_restock(shop_id)
        if not suggestions:
            return {"response": "Δεν χρειάζεται restock αυτή τη στιγμή.", "data": {"suggestions": []},
                    "suggested_actions": [], "intent": "restock"}
        lines = [
            f"- {s['name']} (SKU: {s['sku']}): τώρα {s['current_stock']} → πρόταση +{s['suggested_restock_qty']} (κόστος ~€{s['estimated_cost']:.2f})"
            for s in suggestions
        ]
        return {
            "response": f"Προτάσεις Restock:\n" + "\n".join(lines),
            "data": {"suggestions": suggestions},
            "suggested_actions": [
                {"label": "Export restock list", "action": "export_restock", "params": {}},
            ],
            "intent": "restock",
        }

    async def _handle_shipping(self, shop_id: str, message: str, context: dict | None) -> dict:
        return {
            "response": (
                "Shipping & Labels:\n"
                "Μπορώ να σας βοηθήσω με:\n"
                "- Δημιουργία shipping label\n"
                "- Δημιουργία return label\n"
                "- Οδηγίες συσκευασίας\n"
                "- Σύνοψη για courier\n\n"
                "Δώστε μου τον αριθμό παραγγελίας για να ξεκινήσω."
            ),
            "data": None,
            "suggested_actions": [
                {"label": "Create label", "action": "create_shipping_label", "params": {}},
                {"label": "Packing instructions", "action": "packing_instructions", "params": {}},
            ],
            "intent": "shipping",
        }

    def _help_response(self) -> dict:
        return {
            "response": (
                "Γεια! Είμαι ο Commerce Assistant σου. Μπορώ να σε βοηθήσω με:\n\n"
                "📦 Παραγγελίες: 'Κατάσταση παραγγελίας #12345'\n"
                "🔄 Επιστροφές: 'Πόσες επιστροφές είχαμε αυτή την εβδομάδα;'\n"
                "📊 Stock: 'Ποια προϊόντα έχουν χαμηλό stock;'\n"
                "💀 Dead Stock: 'Ποια προϊόντα δεν πουλάνε;'\n"
                "🎁 Vouchers: 'Στατιστικά vouchers'\n"
                "📈 Έσοδα: 'Πόσα βγάλαμε αυτό τον μήνα;'\n"
                "🚚 Shipping: 'Ετοίμασε label για παραγγελία'\n"
                "🚨 Suspicious: 'Ύποπτα μοτίβα επιστροφών'\n"
                "🏆 Top: 'Ποια προϊόντα πουλάνε πιο πολύ;'\n"
                "❌ Ακυρώσεις: 'Ποιο SKU έχει τις πιο πολλές ακυρώσεις;'\n"
                "📦 Restock: 'Τι πρέπει να παραγγείλω;'"
            ),
            "data": None,
            "suggested_actions": [
                {"label": "Low stock", "action": "low_stock", "params": {}},
                {"label": "Revenue", "action": "revenue", "params": {}},
                {"label": "Returns", "action": "returns_summary", "params": {}},
            ],
            "intent": "help",
        }

    @staticmethod
    def _extract_order_number(message: str) -> str | None:
        match = re.search(r"#?(\d{4,})", message)
        return match.group(1) if match else None

    @staticmethod
    def _extract_sku(message: str) -> str | None:
        match = re.search(r"(?:sku|SKU)[:\s]*([A-Za-z0-9\-_]+)", message)
        return match.group(1) if match else None
