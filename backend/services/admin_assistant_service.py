import asyncio
import json
import logging
import re
from typing import Any, Optional

from core.config import settings

logger = logging.getLogger(__name__)

# Fields the assistant is allowed to propose changes for (dot-notation paths).
# This whitelist is enforced server-side; the commerce server enforces it again on apply.
PROPOSABLE_FIELDS: set[str] = {
    # Theme / visual settings
    "theme.presetId", "theme.menuBg", "theme.menuText", "theme.menuActiveBg",
    "theme.menuActiveText", "theme.buttonRadius", "theme.headerLayout",
    "theme.authPosition", "theme.menuStyle", "theme.heroStyle",
    "theme.categoryMenuStyle", "theme.cardStyle", "theme.sectionSpacing",
    "theme.bannerVisible", "theme.logoDisplayMode", "theme.logoBgMode",
    "theme.logoPadding", "theme.logoRadius", "theme.logoShadow",
    "theme.logoMaxHeight", "theme.productThumbAspect", "theme.productThumbFit",
    "theme.productThumbBg", "theme.productCardHoverEffect", "theme.cardDensity",
    "theme.footerTextColor", "theme.homeLayoutPreset",
    "theme.headerMenuStyle", "theme.colorMode",
    "theme.storefrontBgUrl", "theme.headerHeroLogoOpacity",
    # Branding colours / typography
    "primaryColor", "accentColor", "fontFamily",
    # Virtual-assistant config
    "assistant.vaEnabled", "assistant.vaMode", "assistant.vaLanguage",
    "assistant.vaTone", "assistant.vaBrandVoice", "assistant.vaStoreInstructions",
    "assistant.vaProductGuidance", "assistant.vaCustomerSupport",
    "assistant.vaAvoidTopics", "assistant.vaMerchantGoals",
    # Footer / contact links
    "footer.contactEmail", "footer.facebookUrl", "footer.instagramUrl",
    "footer.tiktokUrl",
    # Notification addresses (sensitive — require password on apply)
    "notifications.notificationEmail", "notifications.replyToEmail",
    "notifications.enabled",
    # Shipping options
    "shippingOptions",
    # Store content
    "heroTitle", "heroText", "heroSubtitle",
    "storeName", "storeDescription",
}

SENSITIVE_FIELDS: set[str] = {
    "notifications.notificationEmail",
    "notifications.replyToEmail",
    "notifications.enabled",
}

# Per-provider AI call budget in seconds.
_AI_TIMEOUT = 20.0

# Maximum tool-use round-trips per user message, to bound latency/cost.
_MAX_TOOL_ROUNDS = 4


# ----------------------------------------------------------------------
# Tool definitions (Anthropic tool-use schema; converted to OpenAI's
# function-calling schema by _to_openai_tools())
# ----------------------------------------------------------------------
ADMIN_TOOLS: list[dict] = [
    {
        "name": "list_products",
        "description": "List all products in the tenant's store with their id, name, price, stock, and category",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_product",
        "description": "Add a new product to the store",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product name"},
                "price": {"type": "number", "description": "Product price in EUR"},
                "description": {"type": "string", "description": "Product description"},
                "category": {"type": "string", "description": "Category slug"},
                "imageUrl": {"type": "string", "description": "Product image URL"},
                "stock": {"type": "integer", "description": "Initial stock quantity"},
            },
            "required": ["name", "price"],
        },
    },
    {
        "name": "update_product",
        "description": "Update an existing product's fields",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product's ID"},
                "updates": {
                    "type": "object",
                    "description": "Fields to update (name, price, description, category, imageUrl, stock)",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "number"},
                        "description": {"type": "string"},
                        "category": {"type": "string"},
                        "imageUrl": {"type": "string"},
                        "stock": {"type": "integer"},
                    },
                },
            },
            "required": ["product_id", "updates"],
        },
    },
    {
        "name": "delete_product",
        "description": "Delete a product from the store",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product's ID to delete"},
            },
            "required": ["product_id"],
        },
    },
    {
        "name": "list_categories",
        "description": "List all categories in the tenant's store",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_category",
        "description": "Add a new category to the store",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Category name"},
                "slug": {"type": "string", "description": "URL-friendly slug"},
                "description": {"type": "string", "description": "Category description"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_shipping_options",
        "description": "List the store's configured shipping options",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_shipping_option",
        "description": "Add a new shipping option (e.g., courier, Box Now locker, pickup)",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Display name (e.g., 'ACS Courier', 'Box Now Locker')"},
                "type": {"type": "string", "description": "Shipping type: courier, boxnow, pickup, local"},
                "base": {"type": "number", "description": "Base shipping cost in EUR"},
                "codFee": {"type": "number", "description": "Cash-on-delivery surcharge"},
            },
            "required": ["label", "base"],
        },
    },
    {
        "name": "list_orders",
        "description": "List recent orders with status, customer, total, and date",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max orders to return (default 20)"},
                "status": {"type": "string", "description": "Filter by status: pending, confirmed, shipped, delivered, cancelled"},
            },
            "required": [],
        },
    },
    {
        "name": "update_store_setting",
        "description": "Update a store configuration field (theme, branding, notifications, footer)",
        "input_schema": {
            "type": "object",
            "properties": {
                "field_path": {"type": "string", "description": "Dot-notation path (e.g., theme.buttonRadius, primaryColor)"},
                "value": {"description": "New value to set"},
            },
            "required": ["field_path", "value"],
        },
    },
]

# Tools that are resolved immediately from tenant_context (no admin approval needed).
READ_TOOLS: set[str] = {"list_products", "list_categories", "list_shipping_options", "list_orders"}

# Tools that mutate store data and must be queued as proposed_actions for admin approval.
WRITE_TOOLS: set[str] = {
    "add_product", "update_product", "delete_product",
    "add_category", "add_shipping_option", "update_store_setting",
}


def _to_openai_tools() -> list[dict]:
    """Convert the Anthropic-style tool defs to OpenAI's function-calling schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in ADMIN_TOOLS
    ]


class AdminAssistantService:
    def __init__(self) -> None:
        self._anthropic = None
        self._openai    = None
        self._init_ai_clients()

    def _init_ai_clients(self) -> None:
        if settings.anthropic_api_key:
            try:
                import anthropic
                self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                logger.warning("[admin-assistant] anthropic package not installed")
        if not self._anthropic and settings.openai_api_key:
            try:
                from openai import AsyncOpenAI
                self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:
                logger.warning("[admin-assistant] openai package not installed")

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_items(items: list, fields: list[str], limit: int = 25) -> str:
        """Render a compact, human-readable summary of a list of dict records."""
        if not items:
            return "(none)"
        lines = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                lines.append(f"  - {item}")
                continue
            parts = [f"{f}={item.get(f)}" for f in fields if f in item]
            lines.append("  - " + ", ".join(parts) if parts else f"  - {item}")
        if len(items) > limit:
            lines.append(f"  ... and {len(items) - limit} more")
        return "\n".join(lines)

    def _build_system_prompt(self, tenant_context: dict, section: Optional[str]) -> str:
        store_name = tenant_context.get("store_name", "")
        if isinstance(store_name, dict):
            store_name = store_name.get("el") or store_name.get("en") or "Unknown"

        tenant_id      = tenant_context.get("tenant_id", "unknown")
        theme          = tenant_context.get("theme", {})
        branding       = tenant_context.get("branding", {})
        assistant_cfg  = tenant_context.get("assistant", {})
        allowed_themes = tenant_context.get("allowed_theme_keys", [])
        support_tier   = tenant_context.get("support_tier", "SELF_SERVICE")

        products         = tenant_context.get("products", []) or []
        categories       = tenant_context.get("categories", []) or []
        shipping_options = tenant_context.get("shipping_options", []) or []
        payment_options  = tenant_context.get("payment_options", []) or []
        recent_orders    = tenant_context.get("recent_orders", []) or []

        prods = len(products) if products else tenant_context.get("products_count", 0)
        cats  = len(categories) if categories else tenant_context.get("categories_count", 0)

        section_note   = (
            f"\nThe admin is currently viewing the **{section}** section."
            if section else ""
        )
        proposable_list = "\n".join(f"  - {f}" for f in sorted(PROPOSABLE_FIELDS))
        sensitive_list  = ", ".join(sorted(SENSITIVE_FIELDS))

        products_summary  = self._summarize_items(products, ["id", "name", "price", "stock", "category"])
        categories_summary = self._summarize_items(categories, ["id", "name", "slug"])
        shipping_summary  = self._summarize_items(shipping_options, ["id", "label", "type", "base", "codFee"])
        payments_summary  = self._summarize_items(payment_options, ["id", "label", "type", "enabled"])
        orders_summary    = self._summarize_items(
            recent_orders, ["id", "status", "customer", "total", "createdAt"], limit=15
        )

        return (
            "You are Βοηθός (Voithos), the AI assistant for tenant administrators "
            "on the Thronos Commerce platform.\n\n"
            "## Your role\n"
            f"You help the administrator of **{store_name}** (tenantId: `{tenant_id}`) "
            "configure their own store only. You can look up store data (products, "
            "categories, shipping options, orders) and propose changes using tools.\n\n"
            "## STRICT TENANT ISOLATION\n"
            "- You ONLY assist with this tenant’s configuration.\n"
            "- You NEVER access, discuss, or propose changes for other tenants.\n"
            "- You NEVER expose global platform config, root admin data, credentials, "
            "or other tenants’ data.\n"
            "- You NEVER directly apply changes. Write operations (adding/updating/deleting "
            "products, categories, shipping options, or store settings) are only ever "
            "**proposed** for the admin to approve — you cannot execute them yourself.\n"
            "- The admin must explicitly approve every proposed change.\n\n"
            "## Current store context\n"
            f"- Store name: {store_name}\n"
            f"- Tenant ID: {tenant_id}\n"
            f"- Support tier: {support_tier}\n"
            f"- Products: {prods}, Categories: {cats}\n"
            f"- Allowed theme keys: {', '.join(allowed_themes) if allowed_themes else 'default'}\n"
            f"- Current theme: {json.dumps(theme, ensure_ascii=False)[:500]}\n"
            f"- Branding: {json.dumps(branding, ensure_ascii=False)[:300]}\n"
            f"- Assistant config: {json.dumps(assistant_cfg, ensure_ascii=False)[:300]}\n"
            "\n### Products (sample)\n"
            f"{products_summary}\n"
            "\n### Categories\n"
            f"{categories_summary}\n"
            "\n### Shipping options\n"
            f"{shipping_summary}\n"
            "\n### Payment methods\n"
            f"{payments_summary}\n"
            "\n### Recent orders (sample)\n"
            f"{orders_summary}\n"
            f"{section_note}\n\n"
            "## Tools available to you\n"
            "You have tools to list products/categories/shipping options/orders (read-only, "
            "resolved immediately), and tools to add/update/delete products, add categories, "
            "add shipping options, and update store settings. Prefer using the up-to-date "
            "list_* tools over the static context above when precise/current data matters — "
            "the context above may be a summary or slightly stale. Every write tool call is "
            "queued as a **proposed action** for the admin to review and approve; nothing is "
            "applied automatically.\n\n"
            "## Legacy proposal format (still supported)\n"
            "For simple config field edits you may alternatively include a JSON block at the "
            "**end** of your response (after your explanation) instead of calling "
            "update_store_setting:\n\n"
            "```json\n"
            "{\n"
            '  "proposed_patches": [\n'
            "    {\n"
            '      "field_path": "theme.buttonRadius",\n'
            '      "current_value": "4px",\n'
            '      "proposed_value": "12px",\n'
            '      "description": "Rounder buttons for a friendlier look",\n'
            '      "requires_password": false\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n\n"
            f"## Proposable fields (ONLY these may be used with update_store_setting or "
            f"proposed_patches)\n"
            f"{proposable_list}\n\n"
            f"Sensitive fields that require admin password: {sensitive_list}\n\n"
            "## Rules\n"
            "1. Always explain the proposal in plain language BEFORE or alongside any tool call.\n"
            "2. Never propose forbidden fields (payment credentials, adminPasswordHash, "
            "raw server config).\n"
            "3. If asked for something outside your scope, decline politely.\n"
            "4. Respond in the same language the admin uses (Greek or English).\n"
            "5. Keep responses concise and actionable.\n"
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_proposed_patches(self, text: str) -> list[dict]:
        """Extract the legacy proposed_patches JSON block from AI output."""
        if not text:
            return []
        pattern = r"```json\s*(\{[\s\S]*?\})\s*```"
        for match in re.findall(pattern, text, re.IGNORECASE):
            try:
                data = json.loads(match)
                raw_patches = data.get("proposed_patches", [])
                if not isinstance(raw_patches, list):
                    continue
                validated = []
                for p in raw_patches:
                    fp = p.get("field_path", "")
                    if fp not in PROPOSABLE_FIELDS:
                        continue
                    validated.append({
                        "field_path"      : fp,
                        "current_value"   : p.get("current_value"),
                        "proposed_value"  : p.get("proposed_value"),
                        "description"     : str(p.get("description", ""))[:500],
                        "requires_password": fp in SENSITIVE_FIELDS,
                    })
                return validated
            except (json.JSONDecodeError, AttributeError):
                continue
        return []

    @staticmethod
    def _clean_response(text: str) -> str:
        """Strip the legacy JSON proposal block from the user-facing response text."""
        if not text:
            return ""
        return re.sub(
            r"```json\s*\{[\s\S]*?\}\s*```", "", text, flags=re.IGNORECASE
        ).strip()

    @staticmethod
    def _get_nested(d: dict, path: str) -> Any:
        cur: Any = d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    # ------------------------------------------------------------------
    # Tool resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_read_tool(name: str, tool_input: dict, tenant_context: dict) -> Any:
        """Resolve a read-only tool call immediately using tenant_context data."""
        if name == "list_products":
            return tenant_context.get("products", []) or []
        if name == "list_categories":
            return tenant_context.get("categories", []) or []
        if name == "list_shipping_options":
            return tenant_context.get("shipping_options", []) or []
        if name == "list_orders":
            orders = tenant_context.get("recent_orders", []) or []
            status = tool_input.get("status")
            if status:
                orders = [o for o in orders if isinstance(o, dict) and o.get("status") == status]
            limit = tool_input.get("limit") or 20
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 20
            return orders[:limit]
        return {"error": f"Unknown read tool '{name}'"}

    def _tool_to_action(
        self, name: str, tool_input: dict, tenant_context: dict
    ) -> tuple[Optional[dict], Optional[dict], Optional[str]]:
        """
        Turn a write-tool call into a proposed_action entry (and, for
        update_store_setting, a matching legacy proposed_patch entry too).

        Returns (action_entry, patch_entry_or_none, error_or_none). Nothing is
        executed here — write tools are never applied by the assistant itself.
        """
        tool_input = tool_input or {}

        if name == "add_product":
            pname = tool_input.get("name", "")
            price = tool_input.get("price")
            desc = f"Add new product '{pname}'" + (f" (€{price})" if price is not None else "")
            return {"action": name, "params": tool_input, "description": desc[:500]}, None, None

        if name == "update_product":
            pid = tool_input.get("product_id", "")
            updates = tool_input.get("updates", {}) or {}
            fields = ", ".join(updates.keys())
            desc = f"Update product {pid}" + (f": {fields}" if fields else "")
            return {"action": name, "params": tool_input, "description": desc[:500]}, None, None

        if name == "delete_product":
            pid = tool_input.get("product_id", "")
            desc = f"Delete product {pid}"
            return {"action": name, "params": tool_input, "description": desc[:500]}, None, None

        if name == "add_category":
            cname = tool_input.get("name", "")
            desc = f"Add new category '{cname}'"
            return {"action": name, "params": tool_input, "description": desc[:500]}, None, None

        if name == "add_shipping_option":
            label = tool_input.get("label", "")
            base = tool_input.get("base")
            desc = f"Add shipping option '{label}'" + (f" (€{base})" if base is not None else "")
            return {"action": name, "params": tool_input, "description": desc[:500]}, None, None

        if name == "update_store_setting":
            field_path = tool_input.get("field_path", "")
            value = tool_input.get("value")
            if field_path not in PROPOSABLE_FIELDS:
                return None, None, f"Field '{field_path}' is not in the proposable fields whitelist"
            current_value = self._get_nested(tenant_context, field_path)
            value_str = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            desc = f"Update {field_path} to {value_str}"
            action_entry = {
                "action": name,
                "params": {"field_path": field_path, "value": value},
                "description": desc[:500],
            }
            patch_entry = {
                "field_path"      : field_path,
                "current_value"   : current_value,
                "proposed_value"  : value,
                "description"     : desc[:500],
                "requires_password": field_path in SENSITIVE_FIELDS,
            }
            return action_entry, patch_entry, None

        return None, None, f"Unknown write tool '{name}'"

    # ------------------------------------------------------------------
    # Anthropic tool-use loop
    # ------------------------------------------------------------------

    async def _anthropic_tool_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        tenant_context: dict,
        tenant_id: str,
    ) -> tuple[Optional[str], list[dict], list[dict]]:
        proposed_actions: list[dict] = []
        proposed_patches: list[dict] = []
        msgs = list(messages)
        final_text: Optional[str] = None

        for _round in range(_MAX_TOOL_ROUNDS):
            try:
                result = await asyncio.wait_for(
                    self._anthropic.messages.create(
                        model      = settings.anthropic_model,
                        max_tokens = 1536,
                        system     = system_prompt,
                        messages   = msgs,
                        tools      = ADMIN_TOOLS,
                    ),
                    timeout=_AI_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[admin-assistant] Anthropic timeout tenant=%s timeout_s=%.1f",
                    tenant_id, _AI_TIMEOUT,
                )
                return final_text, proposed_actions, proposed_patches
            except Exception as exc:
                logger.error(
                    "[admin-assistant] Anthropic error tenant=%s reason=%s",
                    tenant_id, type(exc).__name__,
                )
                return final_text, proposed_actions, proposed_patches

            text_parts: list[str] = []
            tool_use_blocks: list[Any] = []
            assistant_content: list[dict] = []

            for block in result.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)
                    assistant_content.append({
                        "type" : "tool_use",
                        "id"   : block.id,
                        "name" : block.name,
                        "input": block.input,
                    })

            joined = "\n".join(p for p in text_parts if p).strip()
            if joined:
                final_text = joined

            if not tool_use_blocks:
                break

            msgs.append({"role": "assistant", "content": assistant_content})

            tool_results: list[dict] = []
            for block in tool_use_blocks:
                name       = block.name
                tool_input = block.input or {}

                if name in READ_TOOLS:
                    data = self._resolve_read_tool(name, tool_input, tenant_context)
                    tool_results.append({
                        "type"        : "tool_result",
                        "tool_use_id" : block.id,
                        "content"     : json.dumps(data, ensure_ascii=False, default=str)[:8000],
                    })
                elif name in WRITE_TOOLS:
                    action_entry, patch_entry, err = self._tool_to_action(
                        name, tool_input, tenant_context
                    )
                    if err:
                        tool_results.append({
                            "type"        : "tool_result",
                            "tool_use_id" : block.id,
                            "content"     : json.dumps({"error": err}, ensure_ascii=False),
                            "is_error"    : True,
                        })
                    else:
                        proposed_actions.append(action_entry)
                        if patch_entry:
                            proposed_patches.append(patch_entry)
                        tool_results.append({
                            "type"        : "tool_result",
                            "tool_use_id" : block.id,
                            "content"     : json.dumps(
                                {"status": "queued_for_admin_approval", "action": action_entry["action"]},
                                ensure_ascii=False,
                            ),
                        })
                else:
                    tool_results.append({
                        "type"        : "tool_result",
                        "tool_use_id" : block.id,
                        "content"     : json.dumps({"error": f"Unknown tool '{name}'"}, ensure_ascii=False),
                        "is_error"    : True,
                    })

            msgs.append({"role": "user", "content": tool_results})

        return final_text, proposed_actions, proposed_patches

    # ------------------------------------------------------------------
    # OpenAI function-calling loop (fallback)
    # ------------------------------------------------------------------

    async def _openai_tool_loop(
        self,
        system_prompt: str,
        messages: list[dict],
        tenant_context: dict,
        tenant_id: str,
    ) -> tuple[Optional[str], list[dict], list[dict]]:
        proposed_actions: list[dict] = []
        proposed_patches: list[dict] = []
        msgs = [{"role": "system", "content": system_prompt}] + list(messages)
        openai_tools = _to_openai_tools()
        final_text: Optional[str] = None

        for _round in range(_MAX_TOOL_ROUNDS):
            try:
                result = await asyncio.wait_for(
                    self._openai.chat.completions.create(
                        model      = settings.openai_model,
                        max_tokens = 1536,
                        messages   = msgs,
                        tools      = openai_tools,
                    ),
                    timeout=_AI_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "[admin-assistant] OpenAI timeout tenant=%s timeout_s=%.1f",
                    tenant_id, _AI_TIMEOUT,
                )
                return final_text, proposed_actions, proposed_patches
            except Exception as exc:
                logger.error(
                    "[admin-assistant] OpenAI error tenant=%s reason=%s",
                    tenant_id, type(exc).__name__,
                )
                return final_text, proposed_actions, proposed_patches

            choice_msg = result.choices[0].message
            if choice_msg.content:
                final_text = choice_msg.content

            tool_calls = getattr(choice_msg, "tool_calls", None) or []
            if not tool_calls:
                break

            msgs.append({
                "role"      : "assistant",
                "content"   : choice_msg.content or "",
                "tool_calls": [
                    {
                        "id"      : tc.id,
                        "type"    : "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_input = {}

                if name in READ_TOOLS:
                    data = self._resolve_read_tool(name, tool_input, tenant_context)
                    content = json.dumps(data, ensure_ascii=False, default=str)[:8000]
                elif name in WRITE_TOOLS:
                    action_entry, patch_entry, err = self._tool_to_action(
                        name, tool_input, tenant_context
                    )
                    if err:
                        content = json.dumps({"error": err}, ensure_ascii=False)
                    else:
                        proposed_actions.append(action_entry)
                        if patch_entry:
                            proposed_patches.append(patch_entry)
                        content = json.dumps(
                            {"status": "queued_for_admin_approval", "action": action_entry["action"]},
                            ensure_ascii=False,
                        )
                else:
                    content = json.dumps({"error": f"Unknown tool '{name}'"}, ensure_ascii=False)

                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": content})

        return final_text, proposed_actions, proposed_patches

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def process_message(
        self,
        message: str,
        tenant_context: dict,
        section: Optional[str] = None,
        conversation_history: Optional[list] = None,
    ) -> dict:
        system_prompt = self._build_system_prompt(tenant_context, section)
        history       = conversation_history or []

        messages: list[dict] = []
        for h in history[-10:]:
            role = h.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        tenant_id = (tenant_context or {}).get("tenant_id", "unknown")

        final_text: Optional[str] = None
        proposed_actions: list[dict] = []
        proposed_patches: list[dict] = []

        if self._anthropic:
            final_text, proposed_actions, proposed_patches = await self._anthropic_tool_loop(
                system_prompt, messages, tenant_context, tenant_id,
            )

        if final_text is None and self._openai:
            final_text, proposed_actions, proposed_patches = await self._openai_tool_loop(
                system_prompt, messages, tenant_context, tenant_id,
            )

        if final_text is None:
            final_text = (
                "Ο βοηθός δεν είναι διαθέσιμος αυτή τη στιγμή. "
                "Παρακαλώ ελέγξτε τη σύνδεση AI."
            )
            proposed_actions = []
            proposed_patches = []

        # Backward compat: pick up any legacy inline JSON proposed_patches block
        # that the model may still emit, merging by field_path (tool-use results win).
        legacy_patches = self._parse_proposed_patches(final_text)
        if legacy_patches:
            existing_fields = {p["field_path"] for p in proposed_patches}
            for p in legacy_patches:
                if p["field_path"] not in existing_fields:
                    proposed_patches.append(p)
                    existing_fields.add(p["field_path"])

        clean_response = self._clean_response(final_text)

        if any(a.get("action") != "update_store_setting" for a in proposed_actions):
            intent = "admin_action"
        elif proposed_actions or proposed_patches:
            intent = "admin_config"
        else:
            intent = "admin_guidance"

        return {
            "response"        : clean_response,
            "proposed_patches": proposed_patches,
            "proposed_actions": proposed_actions,
            "intent"          : intent,
        }
