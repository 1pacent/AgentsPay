"""x402_discover — Discover agents via x402 Bazaar with taxonomy layer."""

from app.x402 import x402_discover as _x402_discover
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_x402_discover(params: dict) -> dict:
    """Query x402 Bazaar for agents, layered with Track C capability taxonomy.

    Params:
        query (str, optional): Text search (e.g. "LLM text generation")
        category (str, optional): Taxonomy category filter (e.g. "ai/llm")
        max_results (int, optional): Max results (default 20, max 100)
    """
    query = params.get("query")
    if query is not None and not isinstance(query, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'query' must be a string")

    category = params.get("category")
    if category is not None and not isinstance(category, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'category' must be a string")

    max_results = params.get("max_results", 20)
    if not isinstance(max_results, int) or max_results < 1 or max_results > 100:
        max_results = 20

    services = _x402_discover(
        query=query,
        category=category,
        max_results=max_results,
    )

    return {
        "services": services,
        "count": len(services),
        "source": "x402_bazaar",
    }