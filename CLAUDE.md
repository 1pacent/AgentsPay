# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## What this repo is

**AgentPays** — an agent-to-agent (A2A) payment protocol on Base. Autonomous
agents discover each other's capabilities, negotiate a scope of work, pay via
USDC escrow (with x402 support), deliver, verify, and rate each other.

The repo is organized as several loosely-coupled components developed in
parallel "tracks" (see commit history: `Track A`, `Track B`, `Track C`, etc.):

| Path | What it is | Stack |
|---|---|---|
| `src/`, `script/`, `test/` (root) | On-chain smart contracts (Track A/A2/A3) | Solidity / Foundry |
| `agentpays-mcp/` | MCP-compatible JSON-RPC server for agent payments (Track B/B2) | Python / FastAPI |
| `agentpays-index/` | Capability index + A2A agent-card crawler (Track C) | Python / stdlib |
| `agentpays-dogfood/` | End-to-end dogfood script + dashboard (Track E2) | Bash + HTML |

These components are independently runnable. The MCP server talks to the
contracts via `agentpays-mcp/app/chain.py` (mock by default) and to
`agentpays-index`/x402 Bazaar via `agentpays-mcp/app/x402.py`.

---

## 1. Smart Contracts (root: `src/`, `test/`, `script/`)

Foundry project. Solidity `^0.8.20`, `via_ir = true`, optimizer on (200 runs).

### Contracts

- **`src/AgentRegistry.sol`** — on-chain agent registry: register/update/
  deregister agents, discover by capability category, on-chain reputation
  (`trustScore = successfulJobs / totalJobs * 10000`). Owner-only
  `updateReputation` / `emergencyDeregister`.
- **`src/PaymentEscrow.sol`** — USDC escrow state machine:
  `CREATED → FUNDED → (SCOPED) → DELIVERED → COMPLETED`, with
  `REFUNDED`/`CANCELLED` branches.
  - **Tiered protocol fee**: flat $0.002 for orders ≤ $0.10, 1% for
    $0.10–$1.00, 0.5% above $1.00 (`_calcFee`, exposed via `calculateFee`).
  - **Timeouts**: `DEFAULT_BUYER_TIMEOUT` / `DEFAULT_DELIVERY_TIMEOUT` = 6h
    each (overridable per order).
  - **x402 bridge** (`initiateFromX402`): wraps an already-settled x402
    payment into an escrow order starting in `FUNDED` state, with replay
    protection via `usedX402Receipts`.
  - **Scope commitment (Track A2)**: `proposeScope` / `acceptScope` /
    `confirmScopedDelivery`. Trusted agents (`setTrustedAgent`, owner-only)
    get auto-release on scoped delivery; untrusted agents go through normal
    `DELIVERED → releasePayment`.
- **`src/AgentRatings.sol`** — standalone 5-dimension weighted rating system
  (quality 30%, accuracy 25%, speed 15%, communication 15%, would-hire-again
  15%). Tracks buyer tiers by rating *quantity* (Bronze 5+, Silver 25+, Gold
  100+, Platinum 500+) — not score, to avoid inflation incentives. Not yet
  wired into `PaymentEscrow` (`RATING_WINDOW` is a reserved/documentation
  constant; enforcement currently lives in the MCP app layer).
- **`src/mock/MockUSDC.sol`** — 6-decimal mock ERC20 for local testing.

### Security patterns used throughout

- OpenZeppelin `Ownable` + `ReentrancyGuard` on all state-mutating entry
  points.
- `SafeERC20` for all token transfers.
- State-machine guards via `inState` / `onlyBuyer` / `onlySeller` modifiers.
- Checks-effects-interactions ordering. No delegatecall/selfdestruct/raw
  calls.

### Build / test commands

```bash
forge install OpenZeppelin/openzeppelin-contracts   # first-time setup
forge install foundry-rs/forge-std

forge build
forge test                  # default profile (fuzz runs=256)
forge test --gas-report
forge test --profile ci     # fuzz runs=1024, higher verbosity
```

`lib/` (forge-std, openzeppelin-contracts) is gitignored and tracked via
`.gitmodules` + `foundry.lock` — run `forge install` (or
`git submodule update --init`) if `lib/` is missing.

### Deployment

`script/Deploy.s.sol` — `DeployAgentPays` (real Base Sepolia USDC
`0x036CbD53842c5426634e7929541eC2318f3dCF7e`) and `DeployMock` (deploys
`MockUSDC` too). `script/DeployRatings.s.sol` — deploys `AgentRatings`
standalone. Both read `DEPLOYER_PRIVATE_KEY` from env via `vm.envUint`.

```bash
forge script script/Deploy.s.sol:DeployAgentPays \
  --rpc-url base_sepolia --broadcast --verify -vvvv
```

### Conventions

- Tests mirror contract names: `test/AgentRegistry.t.sol`,
  `test/PaymentEscrow.t.sol`, `test/PaymentEscrowScope.t.sol`,
  `test/AgentRatings.t.sol`. Use `forge-std/Test.sol`, `vm.prank` for actor
  switching, fixed mock addresses (`address(0x100)`, etc.) for actors.
- USDC amounts are always 6-decimal integers (e.g. `100_000_000` = 100 USDC).
- Section headers use the `// ─────...─────` box-drawing comment style —
  match it when adding new sections.

---

## 2. MCP Server (`agentpays-mcp/`)

FastAPI JSON-RPC 2.0 server implementing the AgentPays MCP tool surface.

### Architecture

```
POST /mcp --> FastAPI (app/main.py) --> mcp_router.route() --> handlers/*.py
                                                  \--> db.py (SQLite, capability index + orders)
                                                  \--> chain.py (mock | real Web3.py escrow calls)
                                                  \--> wallet.py (eth-account private key)
                                                  \--> x402.py (x402 Bazaar HTTP client + taxonomy)
```

- **`app/main.py`** — FastAPI app. `GET /health`, `POST /mcp`. Validates
  JSON-RPC 2.0 envelope, dispatches to `mcp_router.route`, maps `MCPError`s
  to JSON-RPC error responses. DB initialized on startup.
- **`app/mcp_router.py`** — `HANDLERS` dict mapping method name → handler
  function. **Register every new MCP method here.**
- **`app/handlers/`** — one module per tool: `discover.py`, `order.py`,
  `verify.py`, `status.py`, `refund.py`, `x402_discover.py`, `x402_pay.py`,
  `scope.py` (negotiate/accept scope), `rating.py` (submit rating / agent
  profile). Each handler takes `params: dict` and returns a result dict, or
  raises `MCPError(code, message, data=None)`.
- **`app/db.py`** — SQLite (`data/agentpays.db`, WAL mode). Tables:
  `capability_index` (agent directory) and `orders` (order lifecycle +
  JSON `timeline`). One-connection-per-call, simple/no pooling (MVP).
- **`app/chain.py`** — blockchain abstraction. **Mock vs real is gated by
  `settings.mock_contract`** (`AGENTPAYS_MOCK_CONTRACT`, default `true`).
  Mock functions (`_*_mock`) return fake tx hashes / deterministic profile
  data. Real functions (`_*_real`) currently `raise NotImplementedError` —
  fill these in with `web3.py` calls once contracts are deployed and
  `AGENTPAYS_ESCROW_CONTRACT` / `AGENTPAYS_RPC_URL` are set. **No other files
  should need to change** for the mock→real swap.
- **`app/wallet.py`** — ECDSA wallet via `eth_account`, loaded from
  `AGENTPAYS_WALLET_PRIVATE_KEY`. MVP only; future: Crossmint/Coinbase
  Agentic Wallet.
- **`app/x402.py`** — x402 Bazaar HTTP client (stdlib `urllib` only, no
  extra deps). Discovery (`x402_discover`), payment (`x402_pay`, polls for
  confirmation then optionally calls `initiateFromX402` on-chain via
  `_settle_on_chain`), and a keyword-based capability taxonomy
  (`CAPABILITY_TAXONOMY`, `classify_service`) — mirrors the 10 categories
  used by `agentpays-index`.
- **`app/models.py`** — Pydantic models for the JSON-RPC envelope and each
  tool's params/result, plus `MCP_ERROR_CODES` (standard JSON-RPC codes
  -32700.. plus AgentPays-specific -32001..-32004).
- **`app/config.py`** — single `Settings` dataclass, all fields driven by
  `os.getenv(...)` with defaults. **All new config must go through this
  file** — don't read `os.environ` directly elsewhere (x402.py currently has
  its own `X402Settings` mirroring some of these; follow that pattern for
  x402-specific config, but prefer extending `Settings` for general config).

### MCP methods (registered in `mcp_router.HANDLERS`)

| Method | Handler |
|---|---|
| `agent_pay.discover` | `handle_discover` |
| `agent_pay.order` | `handle_order` |
| `agent_pay.verify` | `handle_verify` |
| `agent_pay.status` | `handle_status` |
| `agent_pay.refund` | `handle_refund` |
| `agent_pay.negotiate_scope` | `handle_negotiate_scope` |
| `agent_pay.accept_scope` | `handle_accept_scope` |
| `agent_pay.submit_rating` | `handle_submit_rating` |
| `agent_pay.get_agent_profile` | `handle_get_agent_profile` |
| `x402.discover` | `handle_x402_discover` |
| `x402.pay` | `handle_x402_pay` |

### Config / environment variables (all in `app/config.py`)

`AGENTPAYS_NETWORK`, `AGENTPAYS_RPC_URL`, `AGENTPAYS_CHAIN_ID`,
`AGENTPAYS_ESCROW_CONTRACT`, `AGENTPAYS_WALLET_PRIVATE_KEY`,
`AGENTPAYS_WALLET_ADDRESS`, `AGENTPAYS_DB_PATH`, `AGENTPAYS_HOST`,
`AGENTPAYS_PORT`, `AGENTPAYS_MOCK_CONTRACT` (default `true`),
`AGENTPAYS_DEFAULT_MAX_PRICE`, `AGENTPAYS_ESCROW_TIMEOUT`,
`X402_BAZAAR_MCP_URL`, `X402_BAZAAR_HTTP_URL`, `X402_API_KEY`.

> Note: the README references `.env.example` but it doesn't currently exist
> in `agentpays-mcp/` — defaults in `config.py` are sufficient to run in mock
> mode.

### Run / test

```bash
cd agentpays-mcp
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # mock mode by default

pytest -v          # tests use FastAPI TestClient + autouse setup_db fixture
```

Tests live in `agentpays-mcp/tests/` (`test_health.py`, `test_discover.py`,
`test_order.py`, `test_verify.py`, `test_status.py`, `test_refund.py`,
`test_x402.py`). `conftest.py` seeds two mock agents (`agent-alpha-001`,
`agent-beta-002`) into a fresh DB before every test.

---

## 3. Capability Index (`agentpays-index/`)

Standalone, **stdlib-only** (plus `requests` for the crawler) Python service
— intentionally zero-FastAPI/zero-pydantic to keep it lightweight.

- **`capability_index.py`** — SQLite schema + CRUD + in-process LRU-ish cache
  (30s TTL). Defines the canonical **10 capability categories**:
  `data_extraction`, `lead_enrichment`, `content_generation`,
  `code_review`, `document_analysis`, `research_summarization`,
  `classification`, `translation`, `data_formatting`, `quality_assurance`.
  (Note: `agentpays-mcp/app/x402.py` has its own, *different*,
  taxonomy/category scheme for x402 Bazaar classification — the two are not
  the same and shouldn't be conflated.)
- **`query_api.py`** — stdlib `http.server`-based API: `GET /health`,
  `GET /query/category`, `GET /query/all`, `GET /cache/clear`,
  `POST /agent/register`.
- **`crawler.py`** — fetches `/.well-known/agent.json` (A2A Agent Card spec)
  from known endpoints and registers discovered agents into the index.
- **`main.py`** — CLI entry point:

```bash
cd agentpays-index
python main.py seed              # seed DB with 10 example agents
python main.py server --port 8080
python main.py query <category> [max_price] [min_trust]
python main.py crawl              # crawl known A2A endpoints
```

---

## 4. Dogfood E2E (`agentpays-dogfood/`)

`dogfood.sh` runs a full 10-step protocol flow against a running MCP server:
discover (x402) → select visibility section → pick seller → negotiate scope
→ commit scope on-chain → pay (x402) → mock delivery → verify/release →
submit 5-dim rating → log transaction → open dashboard.

```bash
cd agentpays-dogfood
cp dogfood.env.example dogfood.env   # edit as needed
source dogfood.env
./dogfood.sh                 # full flow against $MCP_URL (default localhost:8000/mcp)
./dogfood.sh --dry-run        # print steps without making MCP calls
```

`dashboard/index.html` is a static dashboard for viewing the resulting
transaction log (`dogfood-data/transactions.json`). The script degrades
gracefully to mock data if the MCP server isn't reachable or doesn't yet
implement a given method — keep that resilience pattern when extending it.

---

## General conventions for this repo

- **No CI workflows configured yet** (`.github/workflows` doesn't exist) —
  there's no automated gate, so run `forge test` and `pytest` locally before
  considering a change complete.
- **Track-based commit messages**: commits reference the parallel-development
  track they belong to, e.g. `Track A2: hash-commit scope verification on
  PaymentEscrow`, `Track B2: MCP tools for scope negotiation...`. Follow this
  convention for contract/protocol-level changes; plain descriptive messages
  are fine for isolated bugfixes.
- **Mock-first development**: both `agentpays-mcp/app/chain.py` (contract
  calls) and `agentpays-index`/x402 integrations are designed to run fully
  mocked with no live blockchain or external API. When adding new
  integrations, follow the same `_xxx_mock` / `_xxx_real` split gated by a
  settings flag.
- **Money is always USDC, 6 decimals**, both on-chain (`uint256`, e.g.
  `1_000_000` = $1.00) and conceptually in the Python layer (floats in
  dollars at the JSON-RPC layer, e.g. `0.005`). Be careful not to mix the two
  representations when wiring `chain.py` to real contracts.
- Several pieces are explicitly marked as placeholders/future work
  (`NotImplementedError` in `chain.py`, `RATING_WINDOW` not enforced
  on-chain, `_settle_on_chain` returns a placeholder hash). Don't silently
  "fix" these into fake-working code — either implement them properly or
  leave the explicit placeholder/error in place.
