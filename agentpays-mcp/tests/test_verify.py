"""Tests for agent_pay.verify."""


def test_verify_order(client, mcp_payload):
    # First create an order
    create_resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "agentId": "agent-alpha-001",
        "maxPrice": 0.005,
    }))
    order_id = create_resp.json()["result"]["orderId"]
    
    # Verify it
    resp = client.post("/mcp", json=mcp_payload("agent_pay.verify", {
        "orderId": order_id,
        "resultHash": "0xabc123def456",
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["status"] == "complete"
    assert data["result"]["verified"] is True
    assert data["result"]["txHash"] is not None


def test_verify_nonexistent_order(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.verify", {
        "orderId": "nonexistent-uuid",
        "resultHash": "0xdeadbeef",
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32003
