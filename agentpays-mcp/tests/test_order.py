"""Tests for agent_pay.order."""


def test_create_order(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "agentId": "agent-alpha-001",
        "params": {"task": "summarize document", "doc_url": "https://docs.example.com/report.pdf"},
        "maxPrice": 0.005,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["orderId"] is not None
    assert data["result"]["status"] == "escrowed"
    assert data["result"]["escrowTxHash"] is not None


def test_create_order_missing_agent_id(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "maxPrice": 0.01,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data


def test_create_order_default_price(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "agentId": "agent-beta-002",
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["orderId"] is not None
