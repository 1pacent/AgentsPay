"""Blockchain abstraction layer.

MOCK MODE (default): Returns fake tx hashes, no real blockchain calls.
REAL MODE: Web3.py calls against deployed contract (Track A).

Swap from mock -> real:
  1. Set AGENTPAYS_MOCK_CONTRACT=false
  2. Set AGENTPAYS_RPC_URL, AGENTPAYS_ESCROW_CONTRACT
  3. Replace _create_escrow_real, _release_escrow_real etc.
  4. Deploy contract ABI file at app/contract_abi.json
"""

import os
import hashlib
from datetime import datetime, timezone
from typing import Any

from app.config import settings


# Mock helpers

def _mock_tx_hash() -> str:
    raw = f"{datetime.now(timezone.utc).isoformat()}-{os.urandom(8).hex()}"
    return "0x" + hashlib.sha256(raw.encode()).hexdigest()[:64]


# Mock implementations

def _create_escrow_mock(
    buyer_address: str,
    seller_address: str,
    amount: float,
    order_id: str,
) -> dict[str, Any]:
    """Simulate creating an on-chain escrow."""
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "escrowed",
        "block_number": 99999999,
    }


def _release_escrow_mock(order_id: str, result_hash: str) -> dict[str, Any]:
    """Simulate releasing escrow payment."""
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "released",
        "block_number": 100000000,
    }


def _refund_escrow_mock(order_id: str) -> dict[str, Any]:
    """Simulate refunding escrow."""
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "refunded",
        "block_number": 100000001,
    }


# Real implementations (stubs -- Track A fills these)

def _create_escrow_real(
    buyer_address: str,
    seller_address: str,
    amount: float,
    order_id: str,
) -> dict[str, Any]:
    """REAL: Create escrow via smart contract."""
    raise NotImplementedError("Real contract calls -- fill when Track A deploys")


def _release_escrow_real(order_id: str, result_hash: str) -> dict[str, Any]:
    raise NotImplementedError("Real contract calls -- fill when Track A deploys")


def _refund_escrow_real(order_id: str) -> dict[str, Any]:
    raise NotImplementedError("Real contract calls -- fill when Track A deploys")


# Public API

def create_escrow(
    buyer_address: str,
    seller_address: str,
    amount: float,
    order_id: str,
) -> dict[str, Any]:
    if settings.mock_contract:
        return _create_escrow_mock(buyer_address, seller_address, amount, order_id)
    return _create_escrow_real(buyer_address, seller_address, amount, order_id)


def release_escrow(order_id: str, result_hash: str) -> dict[str, Any]:
    if settings.mock_contract:
        return _release_escrow_mock(order_id, result_hash)
    return _release_escrow_real(order_id, result_hash)


def refund_escrow(order_id: str) -> dict[str, Any]:
    if settings.mock_contract:
        return _refund_escrow_mock(order_id)
    return _refund_escrow_real(order_id)


# ─── Scope Commitment (Track A2) ───

def _propose_scope_mock(order_id: str, scope_hash: str, buyer: str) -> dict[str, Any]:
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "scope_proposed",
        "order_id": order_id,
        "scope_hash": scope_hash,
    }

def _accept_scope_mock(order_id: str, scope_hash: str, seller: str) -> dict[str, Any]:
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "scope_accepted",
        "order_id": order_id,
        "scope_hash": scope_hash,
        "state": "SCOPED",
    }

def propose_scope(order_id: str, scope_hash: str, buyer: str) -> dict[str, Any]:
    if settings.mock_contract:
        return _propose_scope_mock(order_id, scope_hash, buyer)
    raise NotImplementedError("Real propose_scope -- fill when contracts deployed")

def accept_scope(order_id: str, scope_hash: str, seller: str) -> dict[str, Any]:
    if settings.mock_contract:
        return _accept_scope_mock(order_id, scope_hash, seller)
    raise NotImplementedError("Real accept_scope -- fill when contracts deployed")


# ─── Agent Ratings (Track A3) ───

def _submit_rating_mock(
    seller: str, order_id: str,
    quality: int, accuracy: int, speed: int,
    communication: int, would_hire_again: int
) -> dict[str, Any]:
    composite = (
        quality * 30 + accuracy * 25 + speed * 15 +
        communication * 15 + would_hire_again * 15
    ) // 100
    return {
        "tx_hash": _mock_tx_hash(),
        "status": "rated",
        "composite": composite,
        "quality": quality,
        "accuracy": accuracy,
        "speed": speed,
        "communication": communication,
        "would_hire_again": would_hire_again,
    }

def _get_agent_profile_mock(agent_address: str) -> dict[str, Any]:
    """Simulate a full agent profile with KYA, ratings, badges."""
    # Deterministic mock data from agent address hash
    addr_hash = int(hashlib.sha256(agent_address.encode()).hexdigest(), 16)
    total_orders = 10 + (addr_hash % 490)
    successful = int(total_orders * (0.7 + (addr_hash % 30) / 100))
    kya_score = int((successful / total_orders) * 100) if total_orders > 0 else 0
    rating_count = min(total_orders, 5 + (addr_hash % 50))
    avg_composite = 3.0 + ((addr_hash % 20) / 10)
    avg_quality = min(5, max(1, avg_composite + (addr_hash % 3 - 1)))
    avg_accuracy = min(5, max(1, avg_composite + (addr_hash % 3 - 1)))
    avg_speed = min(5, max(1, avg_composite + (addr_hash % 3 - 1)))
    avg_comm = min(5, max(1, avg_composite + (addr_hash % 3 - 1)))
    avg_hire = min(5, max(1, avg_composite + (addr_hash % 3 - 1)))

    # Badge logic
    badges = []
    if rating_count >= 500 and avg_composite > 4.0:
        badges.append("ELITE")
    elif rating_count >= 10 and avg_composite >= 4.5:
        badges.append("TOP_RATED")
    elif total_orders < 5 and avg_composite > 4.5:
        badges.append("NEW_TALENT")
    if 5 <= total_orders <= 25 and avg_composite > 4.0:
        badges.append("RISING_STAR")

    return {
        "agent_address": agent_address,
        "kya_score": kya_score,
        "kya_breakdown": {
            "total_orders": total_orders,
            "successful_orders": successful,
            "success_rate": round(successful / total_orders, 2) if total_orders > 0 else 0,
        },
        "ratings": {
            "total_ratings": rating_count,
            "composite": round(avg_composite, 2),
            "breakdown": {
                "quality": round(avg_quality, 2),
                "accuracy": round(avg_accuracy, 2),
                "speed": round(avg_speed, 2),
                "communication": round(avg_comm, 2),
                "would_hire_again": round(avg_hire, 2),
            },
        },
        "badges": badges,
        "order_stats": {
            "total": total_orders,
            "successful": successful,
            "success_rate": round(successful / total_orders, 2) if total_orders > 0 else 0,
            "last_active": "2026-06-13T00:00:00Z",
        },
    }

def submit_rating(
    seller: str, order_id: str,
    quality: int, accuracy: int, speed: int,
    communication: int, would_hire_again: int
) -> dict[str, Any]:
    if settings.mock_contract:
        return _submit_rating_mock(seller, order_id, quality, accuracy, speed, communication, would_hire_again)
    raise NotImplementedError("Real submit_rating -- fill when AgentRatings deployed")

def get_agent_profile(agent_address: str) -> dict[str, Any]:
    if settings.mock_contract:
        return _get_agent_profile_mock(agent_address)
    raise NotImplementedError("Real get_agent_profile -- fill when contracts deployed")
