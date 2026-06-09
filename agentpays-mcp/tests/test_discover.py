"""Tests for agent_pay.discover."""

from tests.conftest import *


def test_discover_by_capability(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.discover", {
        "capability": "data_processing",
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["result"]["count"] == 2
    assert len(data["result"]["agents"]) == 2


def test_discover_with_price_filter(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.discover", {
        "capability": "data_processing",
        "maxPrice": 0.006,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["count"] == 1
    assert data["result"]["agents"][0]["agentId"] == "agent-alpha-001"


def test_discover_with_trust_filter(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.discover", {
        "capability": "data_processing",
        "minTrustScore": 0.85,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["count"] == 1
    assert data["result"]["agents"][0]["trustScore"] >= 0.85


def test_discover_no_match(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.discover", {
        "capability": "quantum_computing",
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["count"] == 0
    assert data["result"]["agents"] == []


def test_discover_missing_capability(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.discover", {}))
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32602
