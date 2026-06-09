"""agent_pay.order -- Create an escrow order."""

from app.config import settings
from app.db import create_order, set_order_tx_hash
from app.chain import create_escrow
from app.wallet import get_address
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_order(params: dict) -> dict:
    agent_id = params.get("agentId")
    max_price = params.get("maxPrice")
    order_params = params.get("params", {})
    
    if not agent_id or not isinstance(agent_id, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'agentId' is required (string)")
    
    if max_price is None:
        max_price = settings.default_max_price
    max_price = float(max_price)
    
    # Get buyer wallet address
    buyer_address = get_address() or "0x0000000000000000000000000000000000000000"
    
    # Create order in DB (pending state)
    order = create_order(
        buyer_agent_id=buyer_address,
        seller_agent_id=agent_id,
        params=order_params,
        price=max_price,
    )
    
    order_id = order["orderId"]
    
    # Create on-chain escrow (mock or real)
    escrow = create_escrow(
        buyer_address=buyer_address,
        seller_address=agent_id,
        amount=max_price,
        order_id=order_id,
    )
    
    # Store tx hash in order record
    if escrow.get("tx_hash"):
        set_order_tx_hash(order_id, escrow["tx_hash"])
    
    return {
        "orderId": order_id,
        "status": "escrowed",
        "escrowTxHash": escrow.get("tx_hash"),
    }
