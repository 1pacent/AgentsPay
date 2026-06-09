"""Tests for agent_pay.refund.

Note: Refund with timeout check will fail in tests because the order
was just created. These tests validate the timeout enforcement.
"""


def test_refund_too_early(client, mcp_payload):
    """Refund should fail because timeout hasn't elapsed."""
    create_resp = client.post("/mcp", json=mcp_payload("agent_pay.order", {
        "agentId": "agent-alpha-001",
        "maxPrice": 0.005,
    }))
    order_id = create_resp.json()["result"]["orderId"]
    
    resp = client.post("/mcp", json=mcp_payload("agent_pay.refund", {
        "orderId": order_id,
    }))
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32004


def test_refund_nonexistent(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.refund", {
        "orderId": "no-such-order",
    }))
    assert resp.status_code == 200
    assert "error" in resp.json()
