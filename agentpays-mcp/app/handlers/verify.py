"""agent_pay.verify -- Mark delivery complete and release escrow."""

from app.db import get_order, update_order_status
from app.chain import release_escrow
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_verify(params: dict) -> dict:
    order_id = params.get("orderId")
    result_hash = params.get("resultHash")
    
    if not order_id or not result_hash:
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'orderId' and 'resultHash' are required")
    
    order = get_order(order_id)
    if order is None:
        code, msg = MCP_ERROR_CODES["ORDER_NOT_FOUND"]
        raise MCPError(code, msg)
    
    current_status = order["status"]
    if current_status not in ("escrowed", "pending"):
        code, msg = MCP_ERROR_CODES["SERVER_ERROR"]
        raise MCPError(code, f"Order {order_id} is in '{current_status}' state -- cannot verify")
    
    # Release escrow on-chain
    tx = release_escrow(order_id, result_hash)
    
    # Update order status
    update_order_status(order_id, "complete", f"Delivery verified. Result hash: {result_hash}")
    
    return {
        "status": "complete",
        "verified": True,
        "txHash": tx.get("tx_hash"),
    }
