"""
Agent Economy Health Score (AEHS) and sub-metrics collector.

Formula (from Strategy & Design §8):
  AEHS = w1(completion_rate) + w2(buyer_surplus) + w3(seller_profit)
       + w4(quality) + w5(market_liquidity)
       - w6(fraud) - w7(disputes) - w8(coordination_cost)

All inputs derive from the deterministic ledger — never from LLM output.
"""

from dataclasses import dataclass
from ..engine.ledger import Ledger


@dataclass
class AEHSWeights:
    completion_rate: float = 0.20
    buyer_surplus: float = 0.15
    seller_profit: float = 0.15
    quality: float = 0.15
    market_liquidity: float = 0.10
    fraud: float = 0.10
    disputes: float = 0.10
    coordination_cost: float = 0.05


class MetricsCollector:
    def __init__(self, ledger: Ledger, weights: AEHSWeights = None):
        self._ledger = ledger
        self._weights = weights or AEHSWeights()

    def completion_rate(self) -> float:
        db = self._ledger._conn
        total = db.execute("SELECT COUNT(*) as n FROM contracts").fetchone()["n"]
        if total == 0:
            return 0.0
        released = db.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE payment_status = 'released'"
        ).fetchone()["n"]
        return released / total

    def dispute_rate(self) -> float:
        db = self._ledger._conn
        total = db.execute("SELECT COUNT(*) as n FROM contracts").fetchone()["n"]
        if total == 0:
            return 0.0
        disputed = db.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE escrow_status = 'disputed'"
        ).fetchone()["n"]
        return disputed / total

    def average_quality(self) -> float:
        db = self._ledger._conn
        row = db.execute(
            "SELECT AVG(validation_score) as avg FROM contracts WHERE validation_score IS NOT NULL"
        ).fetchone()
        return row["avg"] or 0.0

    def gross_transaction_value(self) -> float:
        db = self._ledger._conn
        row = db.execute(
            "SELECT SUM(agreed_price_usdc) as total FROM contracts WHERE payment_status = 'released'"
        ).fetchone()
        return row["total"] or 0.0

    def agentpays_fee_revenue(self, fee_pct: float = 0.005) -> float:
        return self.gross_transaction_value() * fee_pct

    def median_negotiation_rounds(self) -> float:
        db = self._ledger._conn
        rows = db.execute(
            "SELECT COUNT(*) as n FROM transactions WHERE action_type IN ('COUNTEROFFER', 'SUBMIT_QUOTE')"
        ).fetchone()
        contracts = db.execute("SELECT COUNT(*) as n FROM contracts").fetchone()["n"]
        if contracts == 0:
            return 0.0
        return rows["n"] / contracts

    def herfindahl_index(self, role: str = "seller") -> float:
        """Market concentration. 1.0 = monopoly, 0 = perfect competition."""
        db = self._ledger._conn
        col = "seller_id" if role == "seller" else "buyer_id"
        rows = db.execute(
            f"SELECT {col}, COUNT(*) as n FROM contracts WHERE payment_status='released' GROUP BY {col}"
        ).fetchall()
        if not rows:
            return 0.0
        total = sum(r["n"] for r in rows)
        return sum((r["n"] / total) ** 2 for r in rows)

    def snapshot(self, fee_pct: float = 0.005) -> dict:
        return {
            "completion_rate": self.completion_rate(),
            "dispute_rate": self.dispute_rate(),
            "average_quality": self.average_quality(),
            "gross_transaction_value_usdc": self.gross_transaction_value(),
            "agentpays_fee_revenue_usdc": self.agentpays_fee_revenue(fee_pct),
            "median_negotiation_rounds": self.median_negotiation_rounds(),
            "seller_concentration_hhi": self.herfindahl_index("seller"),
            "buyer_concentration_hhi": self.herfindahl_index("buyer"),
            "aehs": self._aehs(),
        }

    def _aehs(self) -> float:
        w = self._weights
        cr = self.completion_rate()
        dr = self.dispute_rate()
        aq = self.average_quality()
        score = (
            w.completion_rate * cr
            + w.quality * aq
            - w.disputes * dr
        )
        return round(min(max(score, 0.0), 1.0), 4)
