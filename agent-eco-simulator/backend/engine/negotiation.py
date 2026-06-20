"""
Negotiation state machine.

Tracks RFQ → quote → counteroffer → accept/reject cycles.
Each negotiation is stored in the ledger. The engine enforces valid
transitions; LLMs decide what terms to propose.

States: OPEN → QUOTED → COUNTERED → ACCEPTED | REJECTED | EXPIRED
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .ledger import Ledger


class NegotiationStatus(str, Enum):
    OPEN = "open"           # RFQ sent, awaiting first quote
    QUOTED = "quoted"       # Seller submitted a quote
    COUNTERED = "countered" # Buyer counter-offered
    ACCEPTED = "accepted"   # Both parties agree — ready to fund escrow
    REJECTED = "rejected"   # One party walked away
    EXPIRED = "expired"     # Max rounds reached without agreement


VALID_TRANSITIONS = {
    NegotiationStatus.OPEN:      {NegotiationStatus.QUOTED, NegotiationStatus.REJECTED},
    NegotiationStatus.QUOTED:    {NegotiationStatus.ACCEPTED, NegotiationStatus.COUNTERED, NegotiationStatus.REJECTED},
    NegotiationStatus.COUNTERED: {NegotiationStatus.QUOTED, NegotiationStatus.ACCEPTED, NegotiationStatus.REJECTED},
    NegotiationStatus.ACCEPTED:  set(),
    NegotiationStatus.REJECTED:  set(),
    NegotiationStatus.EXPIRED:   set(),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS negotiations (
    negotiation_id      TEXT PRIMARY KEY,
    buyer_id            TEXT NOT NULL,
    seller_id           TEXT NOT NULL,
    service_id          TEXT NOT NULL,
    task_description    TEXT NOT NULL,
    max_budget_usdc     REAL NOT NULL,
    quality_threshold   REAL NOT NULL,
    deadline_tick       INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    current_price_usdc  REAL,
    current_scope       TEXT,
    round_count         INTEGER NOT NULL DEFAULT 0,
    max_rounds          INTEGER NOT NULL DEFAULT 5,
    created_tick        INTEGER NOT NULL,
    updated_at          REAL NOT NULL
);
"""


@dataclass
class NegotiationTerms:
    price_usdc: float
    scope_description: str
    delivery_tick: int
    quality_guarantee: float


class NegotiationEngine:
    def __init__(self, ledger: Ledger, max_rounds: int = 5):
        self._ledger = ledger
        self._max_rounds = max_rounds
        ledger._conn.executescript(SCHEMA)
        ledger._conn.commit()

    def open_rfq(
        self,
        buyer_id: str,
        seller_id: str,
        service_id: str,
        task_description: str,
        max_budget_usdc: float,
        quality_threshold: float,
        deadline_tick: int,
        current_tick: int,
    ) -> str:
        neg_id = f"neg_{uuid.uuid4().hex[:10]}"
        self._ledger._conn.execute(
            """INSERT INTO negotiations
               (negotiation_id, buyer_id, seller_id, service_id, task_description,
                max_budget_usdc, quality_threshold, deadline_tick, status,
                round_count, max_rounds, created_tick, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, ?, ?, ?)""",
            (neg_id, buyer_id, seller_id, service_id, task_description,
             max_budget_usdc, quality_threshold, deadline_tick,
             self._max_rounds, current_tick, time.time()),
        )
        self._ledger._conn.commit()
        return neg_id

    def submit_quote(self, negotiation_id: str, terms: NegotiationTerms) -> bool:
        neg = self._get(negotiation_id)
        if not neg:
            return False
        status = NegotiationStatus(neg["status"])
        if NegotiationStatus.QUOTED not in VALID_TRANSITIONS[status]:
            return False
        if terms.price_usdc > neg["max_budget_usdc"] * 1.5:
            # Quote so far above budget it can never close — auto-reject
            return self._transition(negotiation_id, NegotiationStatus.REJECTED, terms)
        return self._transition(negotiation_id, NegotiationStatus.QUOTED, terms)

    def counteroffer(self, negotiation_id: str, terms: NegotiationTerms) -> bool:
        neg = self._get(negotiation_id)
        if not neg:
            return False
        if neg["round_count"] >= neg["max_rounds"] - 1:
            return self._transition(negotiation_id, NegotiationStatus.EXPIRED, terms)
        status = NegotiationStatus(neg["status"])
        if NegotiationStatus.COUNTERED not in VALID_TRANSITIONS[status]:
            return False
        return self._transition(negotiation_id, NegotiationStatus.COUNTERED, terms)

    def accept(self, negotiation_id: str) -> Optional[NegotiationTerms]:
        """Accept current terms. Returns the agreed terms or None if invalid."""
        neg = self._get(negotiation_id)
        if not neg:
            return None
        status = NegotiationStatus(neg["status"])
        if NegotiationStatus.ACCEPTED not in VALID_TRANSITIONS[status]:
            return None
        if not neg["current_price_usdc"]:
            return None
        terms = NegotiationTerms(
            price_usdc=neg["current_price_usdc"],
            scope_description=neg["current_scope"] or "",
            delivery_tick=neg["deadline_tick"],
            quality_guarantee=neg["quality_threshold"],
        )
        self._transition(negotiation_id, NegotiationStatus.ACCEPTED, terms)
        return terms

    def reject(self, negotiation_id: str) -> bool:
        neg = self._get(negotiation_id)
        if not neg:
            return False
        status = NegotiationStatus(neg["status"])
        if NegotiationStatus.REJECTED not in VALID_TRANSITIONS[status]:
            return False
        self._ledger._conn.execute(
            "UPDATE negotiations SET status = 'rejected', updated_at = ? WHERE negotiation_id = ?",
            (time.time(), negotiation_id),
        )
        self._ledger._conn.commit()
        return True

    def get(self, negotiation_id: str) -> Optional[dict]:
        return self._get(negotiation_id)

    def open_for_seller(self, seller_id: str) -> list[dict]:
        rows = self._ledger._conn.execute(
            "SELECT * FROM negotiations WHERE seller_id = ? AND status IN ('open', 'countered')",
            (seller_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def active_for_buyer(self, buyer_id: str) -> list[dict]:
        rows = self._ledger._conn.execute(
            "SELECT * FROM negotiations WHERE buyer_id = ? AND status NOT IN ('accepted', 'rejected', 'expired')",
            (buyer_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _get(self, negotiation_id: str) -> Optional[dict]:
        row = self._ledger._conn.execute(
            "SELECT * FROM negotiations WHERE negotiation_id = ?", (negotiation_id,)
        ).fetchone()
        return dict(row) if row else None

    def _transition(self, negotiation_id: str, new_status: NegotiationStatus, terms: Optional[NegotiationTerms] = None) -> bool:
        updates = {"status": new_status, "updated_at": time.time()}
        if terms:
            updates["current_price_usdc"] = terms.price_usdc
            updates["current_scope"] = terms.scope_description
        neg = self._get(negotiation_id)
        if neg:
            updates["round_count"] = neg["round_count"] + 1
        sets = ", ".join(f"{k} = ?" for k in updates)
        self._ledger._conn.execute(
            f"UPDATE negotiations SET {sets} WHERE negotiation_id = ?",
            list(updates.values()) + [negotiation_id],
        )
        self._ledger._conn.commit()
        return True
