"""x402_pay — Pay for an agent service via x402 protocol with on-chain settlement."""

from app.x402 import x402_pay as _x402_pay
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_x402_pay(params: dict) -> dict:
    """Execute x402 payment flow for an agent service.

    Params:
        service_id (str, required): The service/agent to pay
        amount (str, required): Payment amount (e.g. "10.00")
        currency (str, optional): Currency code (default "USDC")
        auto_settle (bool, optional): Call initiateFromX402 on-chain (default true)
    """
    service_id = params.get("service_id")
    if not service_id or not isinstance(service_id, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'service_id' is required (string)")

    amount = params.get("amount")
    if not amount or not isinstance(amount, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'amount' is required (string)")

    currency = params.get("currency", "USDC")
    if not isinstance(currency, str):
        currency = "USDC"

    auto_settle = params.get("auto_settle", True)
    if not isinstance(auto_settle, bool):
        auto_settle = True

    receipt = _x402_pay(
        service_id=service_id,
        amount=amount,
        currency=currency,
        auto_settle=auto_settle,
    )

    return receipt