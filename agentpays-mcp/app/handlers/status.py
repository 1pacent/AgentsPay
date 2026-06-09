"""agent_pay.status -- Get current order state and timeline."""

from app.db import get_order
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_status(params: dict) -> dict:
    order_id = params.get("orderId")
    if not order_id:
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'orderId' is required")
    
    order = get_order(order_id)
    if order is None:
        code, msg = MCP_ERROR_CODES["ORDER_NOT_FOUND"]
        raise MCPError(code, msg)
    
    return order
