-- AgentPays Database Schema
-- Used by db.py init_db() on startup

CREATE TABLE IF NOT EXISTS capability_index (
    agent_id        TEXT PRIMARY KEY,
    capabilities    TEXT NOT NULL,  -- JSON array
    price_per_call  REAL NOT NULL DEFAULT 0.0,
    trust_score     REAL NOT NULL DEFAULT 0.5,
    endpoint_url    TEXT NOT NULL,
    wallet_address  TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,
    buyer_agent_id  TEXT NOT NULL,
    seller_agent_id TEXT NOT NULL,
    params          TEXT NOT NULL DEFAULT '{}',
    price           REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'pending',
    result_hash     TEXT,
    escrow_tx_hash  TEXT,
    created_at      TEXT NOT NULL,
    timeline        TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (seller_agent_id) REFERENCES capability_index(agent_id)
);
