"""
Economic action types for the Agent Eco Simulator.

These replace MiroFish's social actions (POST, COMMENT, FOLLOW, LIKE, REPOST)
with the transaction lifecycle of the AgentPays protocol.

Each action is a validated event written to the deterministic ledger.
LLMs decide WHICH action to take and WHAT to say; this module enforces
WHAT actually happened.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class ActionType(str, Enum):
    PUBLISH_SERVICE = "PUBLISH_SERVICE"           # Seller registers a capability
    SEARCH_CAPABILITY = "SEARCH_CAPABILITY"       # Buyer queries the registry
    REQUEST_QUOTE = "REQUEST_QUOTE"               # Buyer sends RFQ to matched sellers
    SUBMIT_QUOTE = "SUBMIT_QUOTE"                 # Seller responds with price + scope
    COUNTEROFFER = "COUNTEROFFER"                 # Either party modifies terms
    ACCEPT_SCOPE = "ACCEPT_SCOPE"                 # Both parties lock the contract
    FUND_ESCROW = "FUND_ESCROW"                   # Buyer locks payment
    DELEGATE_TASK = "DELEGATE_TASK"               # Seller subcontracts to another agent
    SUBMIT_DELIVERABLE = "SUBMIT_DELIVERABLE"     # Seller submits work product
    VALIDATE_DELIVERABLE = "VALIDATE_DELIVERABLE" # Automated or buyer-driven quality check
    ACCEPT_DELIVERABLE = "ACCEPT_DELIVERABLE"     # Buyer confirms, triggers payment release
    REJECT_DELIVERABLE = "REJECT_DELIVERABLE"     # Buyer rejects, triggers dispute or retry
    RAISE_DISPUTE = "RAISE_DISPUTE"               # Escalates to dispute-resolution agent
    RELEASE_PAYMENT = "RELEASE_PAYMENT"           # Escrow settles to seller
    REFUND_PAYMENT = "REFUND_PAYMENT"             # Escrow returns to buyer
    RATE_PROVIDER = "RATE_PROVIDER"               # Buyer submits reputation signal


@dataclass
class EconomicAction:
    agent_id: str
    tick: int
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    transaction_id: Optional[str] = None
    action_type: Optional[ActionType] = None

    def validate(self) -> bool:
        """Override in subclasses to enforce action-specific rules."""
        return True


@dataclass
class PublishService(EconomicAction):
    action_type: ActionType = ActionType.PUBLISH_SERVICE

    def validate(self) -> bool:
        required = {"service_id", "capability_type", "description", "price_usdc", "quality_guarantee"}
        return required.issubset(self.payload.keys())


@dataclass
class RequestQuote(EconomicAction):
    action_type: ActionType = ActionType.REQUEST_QUOTE

    def validate(self) -> bool:
        required = {"task_description", "max_budget_usdc", "deadline_tick", "quality_threshold"}
        return required.issubset(self.payload.keys())


@dataclass
class SubmitQuote(EconomicAction):
    action_type: ActionType = ActionType.SUBMIT_QUOTE

    def validate(self) -> bool:
        required = {"rfq_id", "price_usdc", "estimated_ticks", "scope_description"}
        return required.issubset(self.payload.keys())


@dataclass
class FundEscrow(EconomicAction):
    action_type: ActionType = ActionType.FUND_ESCROW

    def validate(self) -> bool:
        required = {"contract_id", "amount_usdc", "seller_id"}
        return required.issubset(self.payload.keys())


@dataclass
class RateProvider(EconomicAction):
    action_type: ActionType = ActionType.RATE_PROVIDER

    def validate(self) -> bool:
        required = {"contract_id", "provider_id", "score", "comment"}
        if not required.issubset(self.payload.keys()):
            return False
        score = self.payload.get("score", -1)
        return isinstance(score, (int, float)) and 0.0 <= score <= 5.0
