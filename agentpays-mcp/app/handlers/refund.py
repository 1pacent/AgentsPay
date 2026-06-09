"""agent_pay.refund -- Trigger refund after timeout."""

from datetime import datetime, timezone

from app.config import settings
from app.db import get_order, update_order_status
from app.chain import refund_escrow
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_refund(params: dict) -> dict:
    order_id = params.get("orderId")
    if not order_id:
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'orderId' is required")
    
    order = get_order(order_id)
    if order is None:
        code, msg = MCP_ERROR_CODES["ORDER_NOT_FOUND"]
        raise MCPError(code, msg)
    
    current_status = order["status"]
    if current_status not in ("pending", "escrowed"):
        code, msg = MCP_ERROR_CODES["SERVER_ERROR"]
        raise MCPError(code, f"Order {order_id} is in '{current_status}' state -- cannot refund")
    
    # Calculate if timeout has elapsed from timeline
    timeline = order.get("timeline", [])
    if not timeline:
        code, msg = MCP_ERROR_CODES["REFUND_NOT_ELIGIBLE"]
        raise MCPError(code, "No timeline available to calculate refund eligibility")
    
    created_event = timeline[0]
    created_at_str = created_event.get("timestamp", "")
    if created_at_str:
        created_at = datetime.fromisoformat(created_at_str)
        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
        if elapsed < settings.escrow_timeout_seconds:
            remaining = settings.escrow_timeout_seconds - elapsed
            code, msg = MCP_ERROR_CODES["REFUND_NOT_ELIGIBLE"]
            raise MCPError(
                code,
                f"Refund not available yet. {remaining:.0f}s remaining before timeout",
            )
    
    # Execute refund on-chain
    tx = refund_escrow(order_id)
    
    # Update order
    update_order_status(order_id, "refunded", "Refund triggered after timeout")
    
    return {
        "orderId": order_id,
        "status": "refunded",
        "refunded": True,
        "txHash": tx.get("tx_hash"),
    }
