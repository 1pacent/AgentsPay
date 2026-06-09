"""Tests for agent_pay.status."""


def test_get_order_status(client, mcp_payload):
    # Create an order first
    create_resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "agentId": "agent-alpha-001",
        "maxPrice": 0.005,
    }))
    order_id = create_resp.json()["result"]["orderId"]
    
    # Get status
    resp = client.post("/mcp", json=mcp_payload("agent_pay.status", {
        "orderId": order_id,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["orderId"] == order_id
    assert data["result"]["status"] is not None
    assert data["result"]["timeline"] is not None
    assert len(data["result"]["timeline"]) >= 1


def test_get_status_nonexistent(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.status", {
        "orderId": "fake-order-id",
    }))
    assert resp.status_code == 200
    assert "error" in resp.json()
