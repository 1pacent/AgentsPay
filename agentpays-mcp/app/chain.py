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
