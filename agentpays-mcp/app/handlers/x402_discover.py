"""x402_discover — Discover agents via x402 Bazaar with taxonomy layer and visibility sections."""

from app.x402 import x402_discover as _x402_discover
from app.chain import get_agent_profile as _get_profile
from app.models import MCP_ERROR_CODES
from app.mcp_router import MCPError


def _compute_badge(profile: dict) -> str | None:
    """Compute section badge from agent profile data."""
    ratings = profile.get("ratings", {})
    rating_count = ratings.get("total_ratings", 0)
    composite = ratings.get("composite", 0)
    order_stats = profile.get("order_stats", {})
    total_orders = order_stats.get("total", 0)

    if rating_count >= 500 and composite > 4.0:
        return "ELITE"
    if rating_count >= 10 and composite >= 4.5:
        return "TOP_RATED"
    if total_orders < 5 and composite > 4.5:
        return "NEW_TALENT"
    if 5 <= total_orders <= 25 and composite > 4.0:
        return "RISING_STAR"
    return None


def _assign_section(profile: dict) -> str:
    """Assign an agent to a visibility section based on profile data."""
    ratings = profile.get("ratings", {})
    rating_count = ratings.get("total_ratings", 0)
    composite = ratings.get("composite", 0)
    order_stats = profile.get("order_stats", {})
    total_orders = order_stats.get("total", 0)

    if rating_count >= 10 and composite >= 4.5:
        return "top_rated"
    if total_orders < 5 and composite > 4.5:
        return "new_talent"
    return "all"


def handle_x402_discover(params: dict) -> dict:
    """Query x402 Bazaar for agents, layered with Track C capability taxonomy.

    Returns results in 3 visibility sections:
        top_rated — agents with 10+ ratings, sorted by composite score
        new_talent — agents with <5 orders but >4.5 composite score
        all — full list with filters (sort, KYA min, price max)

    Params:
        query (str, optional): Text search (e.g. "LLM text generation")
        category (str, optional): Taxonomy category filter (e.g. "ai/llm")
        max_results (int, optional): Max results (default 20, max 100)
        sections (bool, optional): If true, return visibility sections.
            Default true.

    Returns:
        dict: { services, count, source } or
              { sections: { top_rated, new_talent, trending, all }, source }
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

    include_sections = params.get("sections", True)
    if not isinstance(include_sections, bool):
        include_sections = True

    services = _x402_discover(
        query=query,
        category=category,
        max_results=max_results,
    )

    if not include_sections:
        return {
            "services": services,
            "count": len(services),
            "source": "x402_bazaar",
        }

    # Build profiles for section assignment
    sections = {
        "top_rated": [],
        "new_talent": [],
        "trending": [],
        "all": [],
    }

    for svc in services:
        # Each service gets a profile for section assignment
        agent_id = svc.get("id", svc.get("name", ""))
        wallet = svc.get("endpoint", f"0x{agent_id[:40]:0<40}")

        profile = _get_profile(wallet)
        badge = _compute_badge(profile)
        ratings = profile.get("ratings", {})

        entry = {
            "id": svc.get("id"),
            "name": svc.get("name"),
            "description": svc.get("description"),
            "provider": svc.get("provider"),
            "endpoint": svc.get("endpoint"),
            "pricing": svc.get("pricing"),
            "tags": svc.get("tags", []),
            "rating": svc.get("rating", 0),
            "capabilities": svc.get("capabilities", []),
            "badge": badge,
            "composite_rating": ratings.get("composite", 0),
            "rating_count": ratings.get("total_ratings", 0),
            "total_orders": profile.get("order_stats", {}).get("total", 0),
        }

        section = _assign_section(profile)
        sections[section].append(entry)
        sections["all"].append(entry)

    # Sort within sections
    sections["top_rated"].sort(key=lambda x: x.get("composite_rating", 0), reverse=True)
    sections["new_talent"].sort(key=lambda x: x.get("composite_rating", 0), reverse=True)
    sections["all"].sort(key=lambda x: x.get("rating", 0), reverse=True)
    # Trending: sort by total_orders descending
    sections["trending"] = sorted(sections["all"], key=lambda x: x.get("total_orders", 0), reverse=True)[:10]

    return {
        "sections": sections,
        "count": len(services),
        "source": "x402_bazaar",
    }