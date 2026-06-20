"""
Mock USDC wallet system.

Each agent has a simulated USDC balance. The ledger is the source of truth;
this class is a convenience wrapper for budget tracking and spend-limit enforcement.
"""

from typing import Optional
from .ledger import Ledger


class AgentWallet:
    def __init__(self, agent_id: str, ledger: Ledger, initial_balance: float = 0.0):
        self.agent_id = agent_id
        self._ledger = ledger
        if initial_balance > 0:
            self._ledger.credit(agent_id, initial_balance)

    @property
    def balance(self) -> float:
        return self._ledger.get_balance(self.agent_id)["usdc_balance"]

    @property
    def available(self) -> float:
        b = self._ledger.get_balance(self.agent_id)
        return b["usdc_balance"] - b["locked_usdc"]

    @property
    def locked(self) -> float:
        return self._ledger.get_balance(self.agent_id)["locked_usdc"]

    def can_afford(self, amount_usdc: float) -> bool:
        return self.available >= amount_usdc

    def lock(self, amount_usdc: float) -> bool:
        """Lock funds for escrow. Returns False if insufficient available balance."""
        return self._ledger.debit(self.agent_id, amount_usdc)

    def receive(self, amount_usdc: float) -> None:
        """Credit released escrow payment to this wallet."""
        self._ledger.credit(self.agent_id, amount_usdc)

    def summary(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "balance_usdc": self.balance,
            "available_usdc": self.available,
            "locked_usdc": self.locked,
        }
