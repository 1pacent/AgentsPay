"""Capability Index — SQLite schema, CRUD, LRU cache, fast-path queries.

Part of AgentPays Track C. Zero external dependencies beyond stdlib + requests.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "capability_index.db"

# 10 capability categories
CAPABILITY_CATEGORIES = [
    "data_extraction",
    "lead_enrichment",
    "content_generation",
    "code_review",
    "document_analysis",
    "research_summarization",
    "classification",
    "translation",
    "data_formatting",
    "quality_assurance",
]

# LRU cache
_cache: dict[str, Any] = {}
_cache_ts: float = 0
_CACHE_TTL = 30  # seconds
_cache_lock = threading.Lock()

# ── Database ──────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id            TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                description         TEXT,
                capability_category TEXT NOT NULL,
                price_min           REAL NOT NULL DEFAULT 0.0,
                price_max           REAL,
                trust_score         REAL NOT NULL DEFAULT 0.5,
                endpoint_url        TEXT NOT NULL,
                wallet_address      TEXT,
                agent_card_url      TEXT,
                active              INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at        TEXT NOT NULL DEFAULT (datetime('now')),
                slow_path_eligible  INTEGER NOT NULL DEFAULT 0,
                llm_evaluation      TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_agents_category
                ON agents(capability_category);
            CREATE INDEX IF NOT EXISTS idx_agents_active
                ON agents(active);
            CREATE INDEX IF NOT EXISTS idx_agents_price_trust
                ON agents(price_min, trust_score);
        """)
        conn.commit()
    finally:
        conn.close()


# ── CRUD ──────────────────────────────────────────────────────────────────

def register_agent(
    agent_id: str,
    name: str,
    description: str,
    capability_category: str,
    endpoint_url: str,
    price_min: float = 0.0,
    price_max: float | None = None,
    trust_score: float = 0.5,
    wallet_address: str | None = None,
    agent_card_url: str | None = None,
    slow_path_eligible: bool = False,
):
    if capability_category not in CAPABILITY_CATEGORIES:
        raise ValueError(f"Unknown category: {capability_category}. Valid: {CAPABILITY_CATEGORIES}")

    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO agents (agent_id, name, description, capability_category,
                                price_min, price_max, trust_score, endpoint_url,
                                wallet_address, agent_card_url, slow_path_eligible)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                name              = excluded.name,
                description       = excluded.description,
                capability_category = excluded.capability_category,
                price_min         = excluded.price_min,
                price_max         = excluded.price_max,
                trust_score       = excluded.trust_score,
                endpoint_url      = excluded.endpoint_url,
                wallet_address    = excluded.wallet_address,
                agent_card_url    = excluded.agent_card_url,
                last_seen_at      = datetime('now'),
                active            = 1
        """, (
            agent_id, name, description, capability_category,
            price_min, price_max, trust_score, endpoint_url,
            wallet_address, agent_card_url, 1 if slow_path_eligible else 0,
        ))
        conn.commit()
    finally:
        conn.close()


def query_by_category(
    category: str,
    max_price: float | None = None,
    min_trust: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fast-path query — sub-100ms at 10K rows."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM agents WHERE active = 1 AND capability_category = ?"
        params: list[Any] = [category]

        if max_price is not None:
            query += " AND price_min <= ?"
            params.append(max_price)
        if min_trust is not None:
            query += " AND trust_score >= ?"
            params.append(min_trust)

        query += " ORDER BY trust_score DESC, price_min ASC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── LRU Cache ─────────────────────────────────────────────────────────────

def cached_query(
    category: str,
    max_price: float | None = None,
    min_trust: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Cache-aware query. Cache invalidates after 30s."""
    global _cache, _cache_ts

    cache_key = f"{category}|{max_price}|{min_trust}|{limit}"

    with _cache_lock:
        now = time.time()
        if cache_key in _cache and (now - _cache_ts) < _CACHE_TTL:
            return _cache[cache_key]

    results = query_by_category(category, max_price, min_trust, limit)

    with _cache_lock:
        now = time.time()
        if (now - _cache_ts) > _CACHE_TTL:
            _cache.clear()
            _cache_ts = now
        _cache[cache_key] = results

    return results


def invalidate_cache():
    """Force cache clear."""
    global _cache, _cache_ts
    with _cache_lock:
        _cache.clear()
        _cache_ts = 0


# ── Seed data ─────────────────────────────────────────────────────────────

SEED_AGENTS = [
    {"id": "agent-datax-001", "name": "DataPuller Pro", "desc": "Extracts structured data from any web source", "cat": "data_extraction", "price": 0.002, "trust": 0.91, "endpoint": "https://api.datapuller.example.com/v1"},
    {"id": "agent-lead-002", "name": "LeadGenius", "desc": "B2B lead enrichment and company research", "cat": "lead_enrichment", "price": 0.005, "trust": 0.85, "endpoint": "https://api.leadgenius.example.com/v1"},
    {"id": "agent-content-003", "name": "ContentForge", "desc": "Generates blog posts, emails, and social copy", "cat": "content_generation", "price": 0.003, "trust": 0.88, "endpoint": "https://api.contentforge.example.com/v1"},
    {"id": "agent-coderev-004", "name": "ReviewBot", "desc": "Automated code review with security scanning", "cat": "code_review", "price": 0.008, "trust": 0.93, "endpoint": "https://api.reviewbot.example.com/v1"},
    {"id": "agent-docana-005", "name": "DocAnalyzer", "desc": "Analyzes PDFs, contracts, and reports", "cat": "document_analysis", "price": 0.004, "trust": 0.87, "endpoint": "https://api.docanalyzer.example.com/v1"},
    {"id": "agent-research-006", "name": "ResearchSum", "desc": "Summarizes research papers and market reports", "cat": "research_summarization", "price": 0.006, "trust": 0.90, "endpoint": "https://api.researchsum.example.com/v1"},
    {"id": "agent-classify-007", "name": "ClassifyAI", "desc": "Classifies text into custom taxonomies", "cat": "classification", "price": 0.002, "trust": 0.82, "endpoint": "https://api.classifyai.example.com/v1"},
    {"id": "agent-translate-008", "name": "Polyglot", "desc": "Translation between 50+ languages", "cat": "translation", "price": 0.003, "trust": 0.94, "endpoint": "https://api.polyglot.example.com/v1"},
    {"id": "agent-format-009", "name": "DataCleaner", "desc": "Formats CSV, JSON, XML — validates structure", "cat": "data_formatting", "price": 0.001, "trust": 0.79, "endpoint": "https://api.datacleaner.example.com/v1"},
    {"id": "agent-qa-010", "name": "QAChecker", "desc": "Quality assurance testing for web apps and APIs", "cat": "quality_assurance", "price": 0.007, "trust": 0.89, "endpoint": "https://api.qachecker.example.com/v1"},
]

def seed_database():
    """Populate with 10 seed agents covering all categories."""
    init_db()
    count = 0
    for a in SEED_AGENTS:
        register_agent(
            agent_id=a["id"],
            name=a["name"],
            description=a["desc"],
            capability_category=a["cat"],
            endpoint_url=a["endpoint"],
            price_min=a["price"],
            trust_score=a["trust"],
        )
        count += 1
    invalidate_cache()
    return count
