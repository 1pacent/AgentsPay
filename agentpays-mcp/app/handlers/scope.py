"""Scope negotiation and commitment handlers (Track B2)."""

import hashlib
import json

from app.chain import propose_scope as _propose_scope, accept_scope as _accept_scope
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_negotiate_scope(params: dict) -> dict:
    """Off-chain scope negotiation between buyer and seller.

    Buyer proposes a scope with capability, inputs, output_spec,
    acceptance_criteria, deadline, and price. The seller can accept,
    reject, or counter-propose. Both iterate until match or cancel.

    Params:
        order_id (str): Order identifier
        proposed_scope (dict): {
            capability (str): The capability being requested
            inputs (dict, optional): Input parameters
            output_spec (dict, optional): Expected output format
            acceptance_criteria (list, optional): Acceptance criteria
            deadline (str, optional): ISO 8601 deadline
            price (float, optional): Agreed price
        }
        accept (bool, optional): If true, accept the scope immediately.
            Default false (returns scope hash for review).
        action (str, optional): "propose", "accept", "reject", "counter".
            Default "propose".

    Returns:
        dict: { status, scope_hash (if accepted), scope_details, message }
    """
    order_id = params.get("order_id")
    if not order_id or not isinstance(order_id, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'order_id' is required")

    proposed_scope = params.get("proposed_scope")
    if not proposed_scope or not isinstance(proposed_scope, dict):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'proposed_scope' (dict) is required")

    action = params.get("action", "propose")
    if action not in ("propose", "accept", "reject", "counter"):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'action' must be one of: propose, accept, reject, counter")

    # Generate scope hash deterministically from scope content
    scope_hash = "0x" + hashlib.sha256(
        json.dumps(proposed_scope, sort_keys=True).encode()
    ).hexdigest()[:64]

    if action == "propose":
        return {
            "status": "proposed",
            "scope_hash": scope_hash,
            "scope_details": proposed_scope,
            "message": "Scope proposed. Seller can accept, reject, or counter.",
        }

    if action == "accept":
        return {
            "status": "accepted",
            "scope_hash": scope_hash,
            "scope_details": proposed_scope,
            "message": "Scope accepted. Call accept_scope to commit on-chain.",
        }

    if action == "reject":
        return {
            "status": "rejected",
            "scope_hash": scope_hash,
            "message": "Scope rejected. Buyer may propose a revised scope.",
        }

    # Counter-propose
    return {
        "status": "counter_proposed",
        "scope_hash": scope_hash,
        "scope_details": proposed_scope,
        "message": "Counter-proposal made. Buyer may accept, reject, or counter.",
    }


def handle_accept_scope(params: dict) -> dict:
    """Commit a negotiated scope hash on-chain via PaymentEscrow.

    Calls proposeScope/acceptScope on the PaymentEscrow contract.

    Params:
        order_id (str): Order identifier
        scope_hash (str): The agreed scope hash
        buyer (str): Buyer address (for propose)
        seller (str): Seller address (for accept)

    Returns:
        dict: { status, tx_hash, order_id, scope_hash }
    """
    order_id = params.get("order_id")
    if not order_id or not isinstance(order_id, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'order_id' is required")

    scope_hash = params.get("scope_hash")
    if not scope_hash or not isinstance(scope_hash, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'scope_hash' is required")

    buyer = params.get("buyer")
    seller = params.get("seller")

    if not buyer or not isinstance(buyer, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'buyer' is required")

    if not seller or not isinstance(seller, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'seller' is required")

    # Step 1: Buyer proposes scope on-chain
    propose_result = _propose_scope(order_id, scope_hash, buyer)

    # Step 2: Seller accepts scope on-chain
    accept_result = _accept_scope(order_id, scope_hash, seller)

    return {
        "status": "scope_committed",
        "order_id": order_id,
        "scope_hash": scope_hash,
        "buyer": buyer,
        "seller": seller,
        "propose_tx": propose_result.get("tx_hash"),
        "accept_tx": accept_result.get("tx_hash"),
    }