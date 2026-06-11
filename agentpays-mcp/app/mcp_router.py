"""MCP JSON-RPC request router.

Maps method names to handler functions.
Each handler receives `params: dict` and returns a result dict
or raises MCPError with the appropriate error code.
"""

from typing import Any, Callable

from app.models import mcp_error, MCP_ERROR_CODES
from app.handlers import (
    handle_discover,
    handle_order,
    handle_verify,
    handle_status,
    handle_refund,
    handle_x402_discover,
    handle_x402_pay,
)


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data


# Method registry

HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "agent_pay.discover": handle_discover,
    "agent_pay.order": handle_order,
    "agent_pay.verify": handle_verify,
    "agent_pay.status": handle_status,
    "agent_pay.refund": handle_refund,
    # x402 Bazaar integration (V1)
    "x402.discover": handle_x402_discover,
    "x402.pay": handle_x402_pay,
}


# Router

def route(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Route an MCP method call to its handler."""
    if method not in HANDLERS:
        code, msg = MCP_ERROR_CODES["METHOD_NOT_FOUND"]
        return mcp_error(code, f"Method '{method}' not found")

    handler = HANDLERS[method]
    try:
        result = handler(params)
        return {"result": result}  # wrapped for the caller to embed in MCPResponse
    except MCPError as e:
        return mcp_error(e.code, e.message, e.data)
    except Exception as e:
        return mcp_error(-32000, f"Internal error: {str(e)}")