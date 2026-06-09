"""Tests for health endpoint."""


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "network" in data
    assert "mock_contract" in data
    assert data["version"] == "0.1.0"


def test_mcp_method_not_found(client, mcp_payload):
    resp = client.post("/mcp", json=mcp_payload("agent_pay.fly", {}))
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32601


def test_mcp_invalid_json(client):
    resp = client.post("/mcp", content=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400


def test_mcp_missing_jsonrpc(client, mcp_payload):
    resp = client.post("/mcp", json={"method": "agent_pay.discover", "params": {}, "id": 1})
    assert resp.status_code == 400
