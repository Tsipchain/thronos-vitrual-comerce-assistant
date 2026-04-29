"""
Proof of Helpful — architecture placeholder.

This module defines the clean service interface for the optional paid/proof
layer. All blockchain and payment logic lives here and is NOT mixed into
chat routing, UI, or the assistant service.

Free guidance (chat responses, read-only suggestions) is never gated.
Premium actions (bulk catalogue updates, automated email campaigns, etc.)
require an ActionQuote to be created, approved, and paid before execution.

Integration points (stubbed for future implementation):
  - Thronos node: https://node1.thronoschain.org
  - Layer-2 proof: transaction hash stored per action
  - Helpful score: accumulated per tenant, used for reputation / tier unlock
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class QuoteStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID     = "paid"
    APPLIED  = "applied"


@dataclass
class ActionQuote:
    """Represents a proposed premium AI action that requires approval and payment."""
    quote_id: str
    tenant_id: str
    action_type: str          # e.g. "bulk_product_update", "email_campaign"
    description: str
    estimated_cost_usd: float
    payload: dict             # the action parameters (whitelisted, validated before storage)
    status: QuoteStatus = QuoteStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    tx_hash: Optional[str] = None      # L2 proof hash after payment
    helpful_score: float = 0.0         # contribution to tenant reputation score
    result: Optional[dict] = None      # outcome after action is applied


@dataclass
class ProofRecord:
    """Immutable proof that a helpful action was executed."""
    proof_id: str
    quote_id: str
    tenant_id: str
    action_type: str
    tx_hash: str              # Thronos L2 tx hash (stub: empty string until integrated)
    helpful_score: float
    applied_at: datetime
    summary: str              # human-readable outcome


class ProofOfHelpfulService:
    """
    Service interface for the Proof of Helpful layer.

    Usage pattern (all premium actions must follow this flow):

        quote = await svc.create_quote(tenant_id, action_type, description, cost, payload)
        # ... present quote to admin for approval / payment ...
        if approved_and_paid:
            proof = await svc.apply_and_record(quote)
    """

    # Premium action types that require a quote.
    # Free actions (read, suggest, chat) are NOT listed here.
    PREMIUM_ACTIONS: frozenset[str] = frozenset({
        "bulk_product_update",
        "email_campaign_send",
        "automated_seo_rewrite",
        "catalogue_restructure",
    })

    def is_premium(self, action_type: str) -> bool:
        """Return True if this action type requires a quote before execution."""
        return action_type in self.PREMIUM_ACTIONS

    async def create_quote(
        self,
        tenant_id: str,
        action_type: str,
        description: str,
        estimated_cost_usd: float,
        payload: dict,
    ) -> ActionQuote:
        """
        Create a payable action quote for a premium AI action.
        The action is NOT executed yet.
        """
        if not self.is_premium(action_type):
            raise ValueError(f"action_type '{action_type}' is not a premium action")

        quote = ActionQuote(
            quote_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            action_type=action_type,
            description=description,
            estimated_cost_usd=estimated_cost_usd,
            payload=payload,
        )
        # TODO: persist quote to database
        logger.info("ProofOfHelpful: created quote %s for tenant %s", quote.quote_id, tenant_id)
        return quote

    async def approve_quote(self, quote: ActionQuote) -> ActionQuote:
        """Mark a quote as approved (admin confirmed payment)."""
        if quote.status != QuoteStatus.PENDING:
            raise ValueError(f"Quote {quote.quote_id} is not in PENDING state")
        quote.status = QuoteStatus.APPROVED
        quote.approved_at = datetime.now(timezone.utc)
        # TODO: persist state change
        return quote

    async def record_payment(self, quote: ActionQuote, tx_hash: str) -> ActionQuote:
        """
        Record that payment was confirmed on the Thronos L2 chain.
        Stub: in production this verifies tx_hash against the Thronos node.
        """
        if quote.status != QuoteStatus.APPROVED:
            raise ValueError(f"Quote {quote.quote_id} must be APPROVED before payment")
        quote.tx_hash = tx_hash
        quote.status = QuoteStatus.PAID
        # TODO: verify tx_hash via settings.thronos_node_url
        logger.info("ProofOfHelpful: payment recorded quote=%s tx=%s", quote.quote_id, tx_hash)
        return quote

    async def apply_and_record(
        self,
        quote: ActionQuote,
        apply_fn: Any,          # callable(payload) -> dict result
    ) -> ProofRecord:
        """
        Execute the premium action and create an immutable proof record.
        `apply_fn` is injected by the caller to keep this service decoupled
        from business logic.
        """
        if quote.status != QuoteStatus.PAID:
            raise ValueError(f"Quote {quote.quote_id} must be PAID before applying")

        result = await apply_fn(quote.payload)
        quote.status   = QuoteStatus.APPLIED
        quote.result   = result
        # Helpful score contribution: flat 1.0 per successful premium action
        quote.helpful_score = 1.0

        proof = ProofRecord(
            proof_id=str(uuid.uuid4()),
            quote_id=quote.quote_id,
            tenant_id=quote.tenant_id,
            action_type=quote.action_type,
            tx_hash=quote.tx_hash or "",
            helpful_score=quote.helpful_score,
            applied_at=datetime.now(timezone.utc),
            summary=str(result)[:500],
        )
        # TODO: persist proof record (immutable)
        logger.info(
            "ProofOfHelpful: proof created proof=%s tenant=%s action=%s helpful_score=%.1f",
            proof.proof_id, proof.tenant_id, proof.action_type, proof.helpful_score,
        )
        return proof


# Module-level singleton (lazy-initialised per process)
_service: Optional[ProofOfHelpfulService] = None


def get_proof_of_helpful_service() -> ProofOfHelpfulService:
    global _service
    if _service is None:
        _service = ProofOfHelpfulService()
    return _service
