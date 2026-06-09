"""agent_pay.discover -- Query capability index for matching agents."""

from app.db import discover_agents
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_discover(params: dict) -> dict:
    capability = params.get("capability")
    if not capability or not isinstance(capability, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'capability' is required (string)")
    
    max_price = params.get("maxPrice")
    if max_price is not None:
        max_price = float(max_price)
    
    min_trust_score = params.get("minTrustScore")
    if min_trust_score is not None:
        min_trust_score = float(min_trust_score)
    
    agents = discover_agents(
        capability=capability,
        max_price=max_price,
        min_trust_score=min_trust_score,
    )
    
    return {
        "agents": agents,
        "count": len(agents),
    }
