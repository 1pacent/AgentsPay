"""
Deterministic event ledger — the source of truth for all economic state.

Balances, escrow status, deadlines, and payment outcomes live here.
LLM output NEVER overwrites ledger state; LLMs only choose which action
to submit. The ledger validates and records it.
"""

import sqlite3
import json
import time
from pathlib import Path
from typing import Optional
from .actions import EconomicAction


SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  TEXT UNIQUE NOT NULL,
    action_type     TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    tick            INTEGER NOT NULL,
    timestamp       REAL NOT NULL,
    payload         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id         TEXT PRIMARY KEY,
    buyer_id            TEXT NOT NULL,
    seller_id           TEXT NOT NULL,
    service_id          TEXT NOT NULL,
    agreed_price_usdc   REAL,
    escrow_status       TEXT DEFAULT 'none',
    delivery_status     TEXT DEFAULT 'pending',
    validation_score    REAL,
    payment_status      TEXT DEFAULT 'unpaid',
    created_tick        INTEGER NOT NULL,
    deadline_tick       INTEGER,
    updated_at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS balances (
    agent_id        TEXT PRIMARY KEY,
    usdc_balance    REAL NOT NULL DEFAULT 0.0,
    locked_usdc     REAL NOT NULL DEFAULT 0.0,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reputation (
    provider_id     TEXT NOT NULL,
    contract_id     TEXT NOT NULL,
    score           REAL NOT NULL,
    comment         TEXT,
    tick            INTEGER NOT NULL,
    PRIMARY KEY (provider_id, contract_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_agent ON transactions(agent_id);
CREATE INDEX IF NOT EXISTS idx_transactions_tick ON transactions(tick);
CREATE INDEX IF NOT EXISTS idx_contracts_buyer ON contracts(buyer_id);
CREATE INDEX IF NOT EXISTS idx_contracts_seller ON contracts(seller_id);
"""


class Ledger:
    def __init__(self, db_path: str = "simulation.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record_action(self, action: EconomicAction) -> bool:
        if not action.validate():
            return False
        try:
            self._conn.execute(
                """INSERT INTO transactions
                   (transaction_id, action_type, agent_id, tick, timestamp, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    action.transaction_id or f"{action.action_type}_{action.agent_id}_{action.tick}",
                    action.action_type,
                    action.agent_id,
                    action.tick,
                    action.timestamp,
                    json.dumps(action.payload),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_balance(self, agent_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM balances WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row:
            return dict(row)
        return {"agent_id": agent_id, "usdc_balance": 0.0, "locked_usdc": 0.0}

    def credit(self, agent_id: str, amount_usdc: float) -> None:
        now = time.time()
        self._conn.execute(
            """INSERT INTO balances (agent_id, usdc_balance, locked_usdc, updated_at)
               VALUES (?, ?, 0.0, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                   usdc_balance = usdc_balance + excluded.usdc_balance,
                   updated_at = excluded.updated_at""",
            (agent_id, amount_usdc, now),
        )
        self._conn.commit()

    def debit(self, agent_id: str, amount_usdc: float) -> bool:
        bal = self.get_balance(agent_id)
        available = bal["usdc_balance"] - bal["locked_usdc"]
        if available < amount_usdc:
            return False
        self._conn.execute(
            "UPDATE balances SET locked_usdc = locked_usdc + ?, updated_at = ? WHERE agent_id = ?",
            (amount_usdc, time.time(), agent_id),
        )
        self._conn.commit()
        return True

    def get_contract(self, contract_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM contracts WHERE contract_id = ?", (contract_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_contract(self, contract_id: str, **fields) -> None:
        existing = self.get_contract(contract_id)
        fields["updated_at"] = time.time()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._conn.execute(
                f"UPDATE contracts SET {sets} WHERE contract_id = ?",
                list(fields.values()) + [contract_id],
            )
        else:
            fields["contract_id"] = contract_id
            cols = ", ".join(fields.keys())
            placeholders = ", ".join("?" * len(fields))
            self._conn.execute(
                f"INSERT INTO contracts ({cols}) VALUES ({placeholders})",
                list(fields.values()),
            )
        self._conn.commit()

    def query_actions(self, agent_id: Optional[str] = None, tick_from: int = 0, tick_to: Optional[int] = None) -> list:
        query = "SELECT * FROM transactions WHERE tick >= ?"
        params: list = [tick_from]
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if tick_to is not None:
            query += " AND tick <= ?"
            params.append(tick_to)
        query += " ORDER BY tick ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self._conn.close()
