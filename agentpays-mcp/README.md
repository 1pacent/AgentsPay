# AgentPays MCP Server

MCP-compatible JSON-RPC server for agent-to-agent payments.

Built on FastAPI. Part of the AgentPays POC (Track B).

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run (mock mode -- no real blockchain)
cp .env.example .env
# Edit .env to configure
uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /health` - Server health check
- `POST /mcp` - MCP JSON-RPC endpoint

## MCP Tools

All tools are called via `POST /mcp` with JSON-RPC 2.0 payload.

### agent_pay.discover

Find agents by capability, price, and trust score.

```json
{"jsonrpc": "2.0", "method": "agent_pay.discover", "params": {"capability": "data_processing"}, "id": 1}
```

### agent_pay.order

Create an escrow order to pay an agent.

```json
{"jsonrpc": "2.0", "method": "agent_pay.order", "params": {"agentId": "agent-alpha-001", "maxPrice": 0.005}, "id": 1}
```

### agent_pay.verify

Mark delivery as complete and release escrow.

```json
{"jsonrpc": "2.0", "method": "agent_pay.verify", "params": {"orderId": "uuid", "resultHash": "0xabc"}, "id": 1}
```

### agent_pay.status

Get order status and timeline.

```json
{"jsonrpc": "2.0", "method": "agent_pay.status", "params": {"orderId": "uuid"}, "id": 1}
```

### agent_pay.refund

Trigger refund after timeout elapses.

```json
{"jsonrpc": "2.0", "method": "agent_pay.refund", "params": {"orderId": "uuid"}, "id": 1}
```

## Running Tests

```bash
pytest -v
```

## Architecture

```
POST /mcp --> FastAPI --> mcp_router.py --> handlers/ --> db.py (SQLite)
                                                    \--> chain.py (mock | real Web3.py)
                                                    \--> wallet.py (private key | SDK)
```

### Mock -> Real Contract Swap

When Track A (Smart Contracts) deploys:
1. Set `AGENTPAYS_MOCK_CONTRACT=false` in .env
2. Set `AGENTPAYS_ESCROW_CONTRACT` and `AGENTPAYS_RPC_URL`
3. Fill in the `_real_*` functions in `app/chain.py`

No other files change.

## Configuration

See `.env.example` for all options. Config is loaded from environment variables with sensible defaults.

## Future Tracks

- Track C: Capability Index UI
- Track D: A2A Agent Card discovery
- Track E: Dogfood wiring into OpenClaw
- Track F: n8n Community Node
- Track G: Production deployment
