"""A2A Agent Card crawler — fetches agent.json endpoints, parses skills/capabilities.

Part of AgentPays Track C.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from capability_index import register_agent, seed_database, CAPABILITY_CATEGORIES

logger = logging.getLogger("agentpays.crawler")


def parse_agent_card(url: str, timeout: int = 10) -> dict[str, Any] | None:
    """Fetch and parse an A2A agent.json from a URL.

    Reads the standard /.well-known/agent.json endpoint.
    Returns parsed agent data or None on failure.
    """
    try:
        resp = requests.get(url.rstrip("/") + "/.well-known/agent.json", timeout=timeout)
        resp.raise_for_status()
        card = resp.json()
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch agent card from {url}: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON from {url}: {e}")
        return None

    # Extract agent identity
    agent_id = card.get("agent_id") or card.get("name", "").lower().replace(" ", "-")
    name = card.get("name", "Unknown Agent")
    description = card.get("description", "")
    wallet = card.get("wallet_address")

    # Map skills to capability categories
    skills = card.get("skills", []) or card.get("capabilities", [])
    if not skills:
        logger.info(f"No skills found in agent card from {url}")
        return None

    category = _map_to_category(skills)
    if not category:
        logger.info(f"No matching capability category for {url}")
        return None

    pricing = card.get("pricing", {})
    price_min = pricing.get("price_per_call", 0.01) if isinstance(pricing, dict) else 0.01

    trust = card.get("trust_score", 0.5)

    return {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "capability_category": category,
        "endpoint_url": url,
        "price_min": price_min,
        "trust_score": trust,
        "wallet_address": wallet,
        "agent_card_url": url.rstrip("/") + "/.well-known/agent.json",
    }


def _map_to_category(skills: list[str]) -> str | None:
    """Map raw skill names to one of the 10 capability categories.

    Uses keyword matching. For MVP this is deterministic — no LLM calls.
    """
    skill_text = " ".join(s.lower() for s in skills)

    mapping = {
        "data_extraction": ["extract", "scrape", "crawl", "data", "pull"],
        "lead_enrichment": ["lead", "enrich", "enrichment", "b2b"],
        "content_generation": ["write", "generate", "content", "blog", "copy"],
        "code_review": ["code review", "pr review", "review code", "audit"],
        "document_analysis": ["document", "pdf", "contract", "report", "analyze doc"],
        "research_summarization": ["research", "summarize", "summary", "paper"],
        "classification": ["classify", "categorize", "tag", "label"],
        "translation": ["translate", "translation", "language", "localize"],
        "data_formatting": ["format", "clean", "transform", "csv", "json"],
        "quality_assurance": ["qa", "test", "quality", "assurance", "validate"],
    }

    for category, keywords in mapping.items():
        if any(kw in skill_text for kw in keywords):
            return category

    return None


def crawl_seed() -> int:
    """Run the crawler against known agent endpoints and seed the DB."""
    # Known agent endpoints for seed data
    endpoints = [
        "https://api.datapuller.example.com",
        "https://api.leadgenius.example.com",
        "https://api.contentforge.example.com",
        "https://api.reviewbot.example.com",
        "https://api.docanalyzer.example.com",
        "https://api.researchsum.example.com",
        "https://api.classifyai.example.com",
        "https://api.polyglot.example.com",
        "https://api.datacleaner.example.com",
        "https://api.qachecker.example.com",
    ]

    count = 0
    for url in endpoints:
        data = parse_agent_card(url)
        if data:
            register_agent(
                agent_id=data["agent_id"],
                name=data["name"],
                description=data["description"],
                capability_category=data["capability_category"],
                endpoint_url=data["endpoint_url"],
                price_min=data["price_min"],
                trust_score=data["trust_score"],
                wallet_address=data.get("wallet_address"),
                agent_card_url=data.get("agent_card_url"),
            )
            count += 1
        else:
            logger.info(f"Could not parse card at {url} — falling back to seed data")

    # Fallback: use built-in seed data for any that failed
    seed_database()
    logger.info(f"Crawl complete: {count} agents registered from endpoints")
    return count
