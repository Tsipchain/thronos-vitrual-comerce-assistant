import json
import logging
import re
from typing import Optional

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
    # Notification addresses (sensitive - require password on apply side)
    "notifications.notificationEmail", "notifications.replyToEmail",
    "notifications.enabled",
}

SENSITIVE_FIELDS: set[str] = {
    "notifications.notificationEmail",
    "notifications.replyToEmail",
    "notifications.enabled",
}


class AdminAssistantService:
    def __init__(self) -> None:
        self._anthropic = None
        self._openai = None
        self._init_ai_clients()

    def _init_ai_clients(self) -> None:
        if settings.anthropic_api_key:
            try:
                import anthropic
                self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                logger.warning("anthropic package not installed – admin assistant will use OpenAI or fallback")
        if not self._anthropic and settings.openai_api_key:
            try:
                from openai import AsyncOpenAI
                self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:
                logger.warning("openai package not installed – admin assistant will use keyword fallback")

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self, tenant_context: dict, section: Optional[str]) -> str:
        store_name = tenant_context.get("store_name", "")
        if isinstance(store_name, dict):
            store_name = store_name.get("el") or store_name.get("en") or "Unknown"

        tenant_id = tenant_context.get("tenant_id", "unknown")
        theme = tenant_context.get("theme", {})
        branding = tenant_context.get("branding", {})
        assistant_cfg = tenant_context.get("assistant", {})
        categories_count = tenant_context.get("categories_count", 0)
        products_count = tenant_context.get("products_count", 0)
        allowed_themes = tenant_context.get("allowed_theme_keys", [])
        support_tier = tenant_context.get("support_tier", "SELF_SERVICE")

        section_note = (
            f"\nThe admin is currently viewing the **{section}** section."
            if section else ""
        )
        proposable_list = "\n".join(f"  - {f}" for f in sorted(PROPOSABLE_FIELDS))
        sensitive_list = ", ".join(sorted(SENSITIVE_FIELDS))

        return (
            "You are Βοηθός (Voithos), the AI assistant for tenant administrators "
            "on the Thronos Commerce platform.\n\n"
            "## Your role\n"
            f"You help the administrator of **{store_name}** (tenantId: `{tenant_id}`) configure "
            "their own store only.\n\n"
            "## STRICT TENANT ISOLATION\n"
            "- You ONLY assist with this tenant’s configuration.\n"
            "- You NEVER access, discuss, or propose changes for other tenants.\n"
            "- You NEVER expose global platform config, root admin data, credentials, or other tenants’ data.\n"
            "- You NEVER directly apply changes. You only **propose** them.\n"
            "- The admin must explicitly approve every proposed change before it is applied.\n\n"
            "## Current store context\n"
            f"- Store name: {store_name}\n"
            f"- Tenant ID: {tenant_id}\n"
            f"- Support tier: {support_tier}\n"
            f"- Products: {products_count}, Categories: {categories_count}\n"
            f"- Allowed theme keys: {', '.join(allowed_themes) if allowed_themes else 'default'}\n"
            f"- Current theme: {json.dumps(theme, ensure_ascii=False)[:500]}\n"
            f"- Branding: {json.dumps(branding, ensure_ascii=False)[:300]}\n"
            f"- Assistant config: {json.dumps(assistant_cfg, ensure_ascii=False)[:300]}\n"
            f"{section_note}\n\n"
            "## How to propose changes\n"
            "When you want to suggest a config change, include a JSON block at the **end** of your "
            "response (after your explanation):\n\n"
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
            f"## Proposable fields (ONLY these may appear in proposed_patches)\n"
            f"{proposable_list}\n\n"
            f"Sensitive fields that require admin password before applying: {sensitive_list}\n\n"
            "## Rules\n"
            "1. Always explain the proposal in plain language BEFORE the JSON block.\n"
            "2. Never include forbidden fields (payment credentials, adminPasswordHash, raw server config).\n"
            "3. If asked for something outside your scope, decline politely and explain why.\n"
            "4. Respond in the same language the admin uses (Greek or English).\n"
            "5. Keep responses concise and actionable.\n"
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_proposed_patches(self, text: str) -> list[dict]:
        """Extract the proposed_patches JSON block from AI output."""
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
                        "field_path": fp,
                        "current_value": p.get("current_value"),
                        "proposed_value": p.get("proposed_value"),
                        "description": str(p.get("description", ""))[:500],
                        "requires_password": fp in SENSITIVE_FIELDS,
                    })
                return validated
            except (json.JSONDecodeError, AttributeError):
                continue
        return []

    @staticmethod
    def _clean_response(text: str) -> str:
        """Strip the JSON proposal block from the user-facing response text."""
        return re.sub(r"```json\s*\{[\s\S]*?\}\s*```", "", text, flags=re.IGNORECASE).strip()

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
        history = conversation_history or []

        messages: list[dict] = []
        for h in history[-10:]:
            role = h.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        raw_response: Optional[str] = None

        if self._anthropic:
            try:
                result = await self._anthropic.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=1024,
                    system=system_prompt,
                    messages=messages,
                )
                raw_response = result.content[0].text
            except Exception as exc:
                logger.error("Anthropic admin assistant error: %s", exc)

        if raw_response is None and self._openai:
            try:
                all_msgs = [{"role": "system", "content": system_prompt}] + messages
                result = await self._openai.chat.completions.create(
                    model=settings.openai_model,
                    max_tokens=1024,
                    messages=all_msgs,
                )
                raw_response = result.choices[0].message.content
            except Exception as exc:
                logger.error("OpenAI admin assistant error: %s", exc)

        if raw_response is None:
            raw_response = (
                "Ο βοηθός δεν είναι "
                "διαθέσιμος αυτή "
                "τη στιγμή. "
                "Παρακαλώ ελέγξτε "
                "τη σύνδεση AI."
            )

        proposed_patches = self._parse_proposed_patches(raw_response)
        clean_response = self._clean_response(raw_response)

        return {
            "response": clean_response,
            "proposed_patches": proposed_patches,
            "intent": "admin_config" if proposed_patches else "admin_guidance",
        }
