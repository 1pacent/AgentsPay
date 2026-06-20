"""
Mock AgentRegistry — service discovery layer.

Sellers publish capabilities here. Buyers search by capability type,
price range, quality guarantee, and reputation score.
Mirrors the interface of AgentRegistry.sol so Phase 3 swap is clean.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class ServiceListing:
    seller_id: str
    capability_type: str
    description: str
    price_usdc: float
    quality_guarantee: float      # 0.0–1.0 advertised quality
    max_concurrent_jobs: int = 4
    service_id: str = field(default_factory=lambda: f"svc_{uuid.uuid4().hex[:8]}")
    reputation_score: float = 0.0
    completed_jobs: int = 0
    active: bool = True
    tags: list = field(default_factory=list)


class ServiceRegistry:
    def __init__(self):
        self._listings: dict[str, ServiceListing] = {}

    def publish(self, listing: ServiceListing) -> str:
        self._listings[listing.service_id] = listing
        return listing.service_id

    def deactivate(self, service_id: str) -> None:
        if service_id in self._listings:
            self._listings[service_id].active = False

    def search(
        self,
        capability_type: str,
        max_price_usdc: Optional[float] = None,
        min_quality: Optional[float] = None,
        min_reputation: Optional[float] = None,
        limit: int = 10,
    ) -> list[ServiceListing]:
        results = [
            s for s in self._listings.values()
            if s.active
            and s.capability_type == capability_type
            and (max_price_usdc is None or s.price_usdc <= max_price_usdc)
            and (min_quality is None or s.quality_guarantee >= min_quality)
            and (min_reputation is None or s.reputation_score >= min_reputation)
        ]
        results.sort(key=lambda s: (-s.reputation_score, s.price_usdc))
        return results[:limit]

    def get(self, service_id: str) -> Optional[ServiceListing]:
        return self._listings.get(service_id)

    def update_reputation(self, service_id: str, new_score: float) -> None:
        if service_id in self._listings:
            self._listings[service_id].reputation_score = new_score
            self._listings[service_id].completed_jobs += 1

    def all_active(self) -> list[ServiceListing]:
        return [s for s in self._listings.values() if s.active]

    def stats(self) -> dict:
        active = self.all_active()
        if not active:
            return {"total_listings": 0}
        prices = [s.price_usdc for s in active]
        return {
            "total_listings": len(active),
            "capability_types": list({s.capability_type for s in active}),
            "price_min": min(prices),
            "price_max": max(prices),
            "price_avg": sum(prices) / len(prices),
        }
