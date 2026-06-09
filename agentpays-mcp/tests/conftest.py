"""Test fixtures for AgentPays MCP Server."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import init_db, register_agent


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    # Seed a test agent
    register_agent(
        agent_id="agent-alpha-001",
        capabilities=["data_processing", "text_analysis", "csv_export"],
        price_per_call=0.005,
        endpoint_url="https://api.agent-alpha.example.com/process",
        wallet_address="0x1234567890123456789012345678901234567890",
        trust_score=0.92,
    )
    register_agent(
        agent_id="agent-beta-002",
        capabilities=["data_processing", "image_generation"],
        price_per_call=0.008,
        endpoint_url="https://api.agent-beta.example.com/generate",
        wallet_address="0xabcdef1234567890abcdef1234567890abcdef12",
        trust_score=0.78,
    )
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mcp_payload():
    """Helper to build an MCP JSON-RPC request."""
    def _build(method: str, params: dict | None = None, req_id: int = 1):
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id,
        }
    return _build
