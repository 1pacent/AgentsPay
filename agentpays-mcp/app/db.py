"""SQLite capability index and order store."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


def _get_db() -> sqlite3.Connection:
    """Get a thread-safe connection. For MVP, simple approach -- one writer."""
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_db()
    try:
        conn.executescript("""
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

            CREATE INDEX IF NOT EXISTS idx_capability_active 
                ON capability_index(active);
            CREATE INDEX IF NOT EXISTS idx_orders_status 
                ON orders(status);
        """)
        conn.commit()
    finally:
        conn.close()


# Capability Index

def discover_agents(
    capability: str,
    max_price: float | None = None,
    min_trust_score: float | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return ranked list of active agents matching the capability."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        query = """
            SELECT * FROM capability_index 
            WHERE active = 1 
              AND capabilities LIKE ?
        """
        params = [f"%{capability}%"]
        
        if max_price is not None:
            query += " AND price_per_call <= ?"
            params.append(max_price)
        if min_trust_score is not None:
            query += " AND trust_score >= ?"
            params.append(min_trust_score)
        
        query += " ORDER BY trust_score DESC, price_per_call ASC LIMIT ?"
        params.append(limit)
        
        cur.execute(query, params)
        rows = cur.fetchall()
        
        return [
            {
                "agentId": r["agent_id"],
                "capabilities": json.loads(r["capabilities"]),
                "pricePerCall": r["price_per_call"],
                "trustScore": r["trust_score"],
                "endpointUrl": r["endpoint_url"],
                "walletAddress": r["wallet_address"] or "",
            }
            for r in rows
        ]
    finally:
        conn.close()


def register_agent(
    agent_id: str,
    capabilities: list[str],
    price_per_call: float,
    endpoint_url: str,
    wallet_address: str | None = None,
    trust_score: float = 0.5,
):
    """Register or update an agent in the index."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO capability_index (agent_id, capabilities, price_per_call, trust_score, endpoint_url, wallet_address, active, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                capabilities = excluded.capabilities,
                price_per_call = excluded.price_per_call,
                trust_score = excluded.trust_score,
                endpoint_url = excluded.endpoint_url,
                wallet_address = excluded.wallet_address,
                last_seen_at = excluded.last_seen_at
        """, (
            agent_id,
            json.dumps(capabilities),
            price_per_call,
            trust_score,
            endpoint_url,
            wallet_address,
            now,
            now,
        ))
        conn.commit()
    finally:
        conn.close()


# Orders

def create_order(
    buyer_agent_id: str,
    seller_agent_id: str,
    params: dict,
    price: float,
) -> dict[str, Any]:
    """Create a new order in pending state."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        order_id = str(uuid.uuid4())
        timeline = json.dumps([{
            "event": "created",
            "timestamp": now,
            "detail": f"Order created by {buyer_agent_id} for {seller_agent_id} at ${price:.4f}",
        }])
        
        conn.execute("""
            INSERT INTO orders (order_id, buyer_agent_id, seller_agent_id, params, price, status, created_at, timeline)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (order_id, buyer_agent_id, seller_agent_id, json.dumps(params), price, now, timeline))
        conn.commit()
        
        return {
            "orderId": order_id,
            "status": "pending",
            "escrowTxHash": None,
        }
    finally:
        conn.close()


def get_order(order_id: str) -> dict[str, Any] | None:
    """Get order by ID."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "orderId": row["order_id"],
            "status": row["status"],
            "timeline": json.loads(row["timeline"]),
        }
    finally:
        conn.close()


def update_order_status(order_id: str, status: str, event_note: str = ""):
    """Update order status and append timeline entry."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT timeline, status FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
        if row is None:
            return None
        
        now = datetime.now(timezone.utc).isoformat()
        timeline = json.loads(row["timeline"])
        timeline.append({
            "event": status,
            "timestamp": now,
            "detail": event_note,
            "previous_status": row["status"],
        })
        
        conn.execute(
            "UPDATE orders SET status = ?, timeline = ? WHERE order_id = ?",
            (status, json.dumps(timeline), order_id),
        )
        conn.commit()
        return {"orderId": order_id, "status": status, "timeline": timeline}
    finally:
        conn.close()


def set_order_tx_hash(order_id: str, tx_hash: str):
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE orders SET escrow_tx_hash = ? WHERE order_id = ?",
            (tx_hash, order_id),
        )
        conn.commit()
    finally:
        conn.close()
