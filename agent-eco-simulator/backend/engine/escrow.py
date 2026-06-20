"""
Escrow state machine.

States: none → funded → submitted → validated → released | disputed | refunded

The ledger records every state transition. This module enforces valid
transitions and triggers wallet credits/debits accordingly.
"""

from enum import Enum
from typing import Optional
from .ledger import Ledger
from .wallet import AgentWallet


class EscrowStatus(str, Enum):
    NONE = "none"
    FUNDED = "funded"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    RELEASED = "released"
    DISPUTED = "disputed"
    REFUNDED = "refunded"


VALID_TRANSITIONS = {
    EscrowStatus.NONE:       {EscrowStatus.FUNDED},
    EscrowStatus.FUNDED:     {EscrowStatus.SUBMITTED, EscrowStatus.REFUNDED},
    EscrowStatus.SUBMITTED:  {EscrowStatus.VALIDATED, EscrowStatus.DISPUTED, EscrowStatus.REFUNDED},
    EscrowStatus.VALIDATED:  {EscrowStatus.RELEASED, EscrowStatus.DISPUTED},
    EscrowStatus.RELEASED:   set(),
    EscrowStatus.DISPUTED:   {EscrowStatus.RELEASED, EscrowStatus.REFUNDED},
    EscrowStatus.REFUNDED:   set(),
}


class Escrow:
    def __init__(self, contract_id: str, ledger: Ledger):
        self.contract_id = contract_id
        self._ledger = ledger

    @property
    def status(self) -> EscrowStatus:
        contract = self._ledger.get_contract(self.contract_id)
        if not contract:
            return EscrowStatus.NONE
        return EscrowStatus(contract.get("escrow_status", "none"))

    def _transition(self, new_status: EscrowStatus) -> bool:
        current = self.status
        if new_status not in VALID_TRANSITIONS[current]:
            return False
        self._ledger.upsert_contract(self.contract_id, escrow_status=new_status)
        return True

    def fund(self, buyer_wallet: AgentWallet, amount_usdc: float, seller_id: str, deadline_tick: int) -> bool:
        if not buyer_wallet.can_afford(amount_usdc):
            return False
        if not buyer_wallet.lock(amount_usdc):
            return False
        self._ledger.upsert_contract(
            self.contract_id,
            buyer_id=buyer_wallet.agent_id,
            seller_id=seller_id,
            agreed_price_usdc=amount_usdc,
            deadline_tick=deadline_tick,
            escrow_status=EscrowStatus.FUNDED,
            created_tick=0,
        )
        return True

    def submit_deliverable(self, validation_score: Optional[float] = None) -> bool:
        if not self._transition(EscrowStatus.SUBMITTED):
            return False
        if validation_score is not None:
            self._ledger.upsert_contract(
                self.contract_id,
                delivery_status="submitted",
                validation_score=validation_score,
            )
        return True

    def validate(self, score: float) -> bool:
        self._ledger.upsert_contract(self.contract_id, validation_score=score)
        return self._transition(EscrowStatus.VALIDATED)

    def release(self, seller_wallet: AgentWallet) -> bool:
        contract = self._ledger.get_contract(self.contract_id)
        if not contract:
            return False
        if not self._transition(EscrowStatus.RELEASED):
            return False
        amount = contract["agreed_price_usdc"]
        seller_wallet.receive(amount)
        self._ledger.upsert_contract(self.contract_id, payment_status="released")
        return True

    def refund(self, buyer_wallet: AgentWallet) -> bool:
        contract = self._ledger.get_contract(self.contract_id)
        if not contract:
            return False
        if not self._transition(EscrowStatus.REFUNDED):
            return False
        amount = contract["agreed_price_usdc"]
        buyer_wallet.receive(amount)
        self._ledger.upsert_contract(self.contract_id, payment_status="refunded")
        return True

    def raise_dispute(self) -> bool:
        return self._transition(EscrowStatus.DISPUTED)
