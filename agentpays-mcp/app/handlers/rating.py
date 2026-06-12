"""Rating and profile handlers (Track B2)."""

from app.chain import submit_rating as _submit_rating, get_agent_profile as _get_profile
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def handle_submit_rating(params: dict) -> dict:
    """Submit a 5-dimension rating for a completed delivery.

    Calls AgentRatings.submitRating() on-chain.

    Params:
        seller_address (str): Agent address being rated
        order_id (str): Order identifier
        quality (int): 1-5
        accuracy (int): 1-5
        speed (int): 1-5
        communication (int): 1-5
        would_hire_again (int): 1-5
        comment (str, optional): Off-chain comment reference

    Returns:
        dict: { status, tx_hash, composite, breakdown }
    """
    seller = params.get("seller_address")
    if not seller or not isinstance(seller, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'seller_address' is required")

    order_id = params.get("order_id")
    if not order_id or not isinstance(order_id, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'order_id' is required")

    def _validate_dimension(value: int, name: str) -> int:
        if not isinstance(value, int) or value < 1 or value > 5:
            code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
            raise MCPError(code, f"{msg}: '{name}' must be integer 1-5, got {value}")
        return value

    quality = _validate_dimension(params.get("quality", 3), "quality")
    accuracy = _validate_dimension(params.get("accuracy", 3), "accuracy")
    speed = _validate_dimension(params.get("speed", 3), "speed")
    communication = _validate_dimension(params.get("communication", 3), "communication")
    would_hire_again = _validate_dimension(params.get("would_hire_again", 3), "would_hire_again")

    result = _submit_rating(seller, order_id, quality, accuracy, speed, communication, would_hire_again)

    return {
        "status": result.get("status", "rated"),
        "tx_hash": result.get("tx_hash"),
        "rating_id": f"rating-{order_id}",
        "composite": result.get("composite"),
        "breakdown": {
            "quality": result.get("quality"),
            "accuracy": result.get("accuracy"),
            "speed": result.get("speed"),
            "communication": result.get("communication"),
            "would_hire_again": result.get("would_hire_again"),
        },
    }


def handle_get_agent_profile(params: dict) -> dict:
    """Get full agent profile with KYA, ratings, badges, and order stats.

    Params:
        agent_address (str): The agent's wallet address

    Returns:
        dict: Full profile with KYA score/breakdown, rating breakdown,
              badges, and order statistics.
    """
    agent_address = params.get("agent_address")
    if not agent_address or not isinstance(agent_address, str):
        code, msg = MCP_ERROR_CODES["INVALID_PARAMS"]
        raise MCPError(code, f"{msg}: 'agent_address' is required")

    return _get_profile(agent_address)