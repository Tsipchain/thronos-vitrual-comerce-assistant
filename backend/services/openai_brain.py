"""
OpenAI-powered brain for the Commerce Assistant.
Called first by process_message(); keyword handlers are the fallback.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

MERCHANT_SYSTEM = """You are a smart commerce assistant for a Thronos merchant.
Help with order management, inventory, returns, revenue analytics, and shipping.
Answer in the same language the merchant uses (Greek or English).
Be concise and actionable. If you need a specific order number or SKU, ask for it.
Never invent data — if you don't have it, say so clearly.
"""

CUSTOMER_SYSTEM = """You are a helpful customer support assistant for an online shop.
Help customers with order status, returns, shipping, and product questions.
Answer in the same language the customer uses (Greek or English).
Be friendly, empathetic, and concise. Do not share internal business metrics.
If you cannot resolve the issue, suggest contacting support.
"""


async def ask_openai(
    message: str,
    role: str,
    shop_context: Optional[dict],
    api_key: str,
    model: str = "gpt-4o-mini",
) -> Optional[dict]:
    """Send message to OpenAI; return ChatResponse-compatible dict or None on failure."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.debug("openai package not installed — skipping AI brain")
        return None

    system = CUSTOMER_SYSTEM if role == "customer" else MERCHANT_SYSTEM

    if shop_context:
        parts = []
        if shop_context.get("shop_name"):
            parts.append(f"Shop: {shop_context['shop_name']}")
        if shop_context.get("currency"):
            parts.append(f"Currency: {shop_context['currency']}")
        if shop_context.get("return_window_days"):
            parts.append(f"Return window: {shop_context['return_window_days']} days")
        if parts:
            system += "\n\nContext: " + ", ".join(parts)

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            max_tokens=600,
            temperature=0.4,
        )
        answer = resp.choices[0].message.content.strip()
        return {"response": answer, "data": None, "suggested_actions": [], "intent": "ai"}
    except Exception as exc:
        logger.warning(f"OpenAI call failed: {exc}")
        return None
