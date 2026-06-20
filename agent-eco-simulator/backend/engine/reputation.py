"""
Pluggable reputation calculators.

Four algorithms, all implementing the same interface so they can be
swapped in config and compared in the same simulation run.
"""

import math
from typing import Protocol
from .ledger import Ledger


class ReputationAlgorithm(Protocol):
    def score(self, provider_id: str, ledger: Ledger, current_tick: int) -> float:
        ...


class StarRating:
    """Simple mean of all submitted ratings."""

    def score(self, provider_id: str, ledger: Ledger, current_tick: int) -> float:
        rows = ledger._conn.execute(
            "SELECT score FROM reputation WHERE provider_id = ?", (provider_id,)
        ).fetchall()
        if not rows:
            return 0.0
        return sum(r["score"] for r in rows) / len(rows)


class CompletionRate:
    """Ratio of released payments to total contracts as a seller."""

    def score(self, provider_id: str, ledger: Ledger, current_tick: int) -> float:
        total = ledger._conn.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE seller_id = ?", (provider_id,)
        ).fetchone()["n"]
        if total == 0:
            return 0.0
        released = ledger._conn.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE seller_id = ? AND payment_status = 'released'",
            (provider_id,),
        ).fetchone()["n"]
        return released / total


class TimeDecayed:
    """Star rating with exponential decay — recent ratings matter more."""

    def __init__(self, half_life_ticks: int = 500):
        self.half_life = half_life_ticks

    def score(self, provider_id: str, ledger: Ledger, current_tick: int) -> float:
        rows = ledger._conn.execute(
            "SELECT score, tick FROM reputation WHERE provider_id = ?", (provider_id,)
        ).fetchall()
        if not rows:
            return 0.0
        total_weight = 0.0
        weighted_sum = 0.0
        for r in rows:
            age = current_tick - r["tick"]
            weight = math.exp(-age * math.log(2) / self.half_life)
            weighted_sum += r["score"] * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else 0.0


class VerifiedDelivery:
    """Weighted by validation score — only counts contracts with confirmed quality."""

    def score(self, provider_id: str, ledger: Ledger, current_tick: int) -> float:
        rows = ledger._conn.execute(
            """SELECT r.score, c.validation_score
               FROM reputation r
               JOIN contracts c ON r.contract_id = c.contract_id
               WHERE r.provider_id = ? AND c.validation_score IS NOT NULL""",
            (provider_id,),
        ).fetchall()
        if not rows:
            return 0.0
        weighted_sum = sum(r["score"] * r["validation_score"] for r in rows)
        weight_total = sum(r["validation_score"] for r in rows)
        return weighted_sum / weight_total if weight_total > 0 else 0.0


ALGORITHMS: dict[str, ReputationAlgorithm] = {
    "star_rating": StarRating(),
    "completion_rate": CompletionRate(),
    "time_decayed": TimeDecayed(),
    "verified_delivery": VerifiedDelivery(),
}


def get_algorithm(name: str) -> ReputationAlgorithm:
    if name not in ALGORITHMS:
        raise ValueError(f"Unknown reputation algorithm '{name}'. Choose from: {list(ALGORITHMS)}")
    return ALGORITHMS[name]
