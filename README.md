# AgentPays — Smart Contracts

Agent-to-agent payment protocol on Base. On-chain agent registry and USDC escrow with timeout-based dispute resolution.

## Architecture

```
Agent Registry (AgentRegistry.sol)
├── registerAgent() — Register with capabilities + pricing
├── updateRegistration() — Update agent details
├── deregisterAgent() — Remove from index
├── discover() — Search by capability category
└── updateReputation() — On-chain trust scoring

Payment Escrow (PaymentEscrow.sol)
├── createOrder() → CREATED
├── deposit() → FUNDED
├── confirmDelivery() → DELIVERED
├── releasePayment() → COMPLETED
├── refund() → REFUNDED (timeout)
└── cancelOrder() → CANCELLED
```

### State Machine

```
CREATED ──deposit()──→ FUNDED ──confirmDelivery()──→ DELIVERED ──releasePayment()──→ COMPLETED
  │                       │                              │
  └──cancelOrder()──→     │                              │
  CANCELLED               └──refund()──→ REFUNDED        │
                                  (buyer)                 └──refund()──→ REFUNDED
                                                     (anyone after timeout)
```

## Contracts

| Contract | Lines | Purpose |
|---|---|---|
| `AgentRegistry.sol` | ~175 | Agent CRUD, capability discovery, on-chain reputation |
| `PaymentEscrow.sol` | ~290 | USDC escrow with 5-state machine, 0.5% protocol fee |
| `MockUSDC.sol` | ~20 | 6-decimal mock ERC20 for testing |

## Key Parameters

| Parameter | Value |
|---|---|
| Settlement | USDC (6 decimals) |
| Protocol fee | 0.5% (50 bps, paid by seller) |
| Buyer deposit timeout | 6 hours (configurable) |
| Delivery timeout | 6 hours (configurable) |
| Dispute V1 | Timeout-only (no arbitrator) |
| Reputation | `successfulJobs / totalJobs * 10000` |

## Test Coverage

**22 tests** (AgentRegistry: 11, PaymentEscrow: 11) + 2 fuzz suites

Covers:
- Full happy path: create → deposit → confirm → release → withdraw fees
- All revert conditions (duplicate, zero price, self-order, wrong caller)
- All state transitions (cancel, refund at each stage)
- Timeout mechanisms (delivery timeout, confirm timeout)
- Access control (buyer-only, seller-only, owner-only)
- Reputation scoring
- Protocol fee calculation and withdrawal

## Prerequisites

- [Foundry](https://book.getfoundry.sh/getting-started/installation)
- Base Sepolia RPC URL (e.g. from Alchemy, Infura, or public endpoint)

## Setup

```bash
# Install dependencies
forge install OpenZeppelin/openzeppelin-contracts
forge install foundry-rs/forge-std

# Build
forge build

# Run tests
forge test

# Run tests with gas report
forge test --gas-report

# Run with fuzz (CI profile)
forge test --profile ci
```

## Deployment

### Base Sepolia (Testnet)

```bash
export DEPLOYER_PRIVATE_KEY=0x...
export BASE_SEPOLIA_RPC_URL=https://sepolia.base.org
export BASESCAN_API_KEY=...

forge script script/Deploy.s.sol:DeployAgentPays \
  --rpc-url base_sepolia \
  --broadcast \
  --verify \
  -vvvv
```

### Local / Mock

```bash
export DEPLOYER_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80

forge script script/Deploy.s.sol:DeployMock \
  --rpc-url base_sepolia \
  --broadcast \
  -vvvv
```

## Deployed Addresses

*(To be updated after deployment)*

| Contract | Base Sepolia |
|---|---|
| AgentRegistry | `TBD` |
| PaymentEscrow | `TBD` |
| USDC (Base Sepolia) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |

## Security

- OpenZeppelin `ReentrancyGuard` on all state-mutating functions
- OpenZeppelin `Ownable` for admin (owner-only fee withdrawal, reputation updates)
- OpenZeppelin `SafeERC20` for all USDC transfers
- State-machine guards via modifier (`onlyState`)
- Checks-effects-interactions pattern
- No delegatecall, no selfdestruct, no low-level calls to arbitrary addresses

## Related

- [AgentsPay MCP Server](https://github.com/1pacent/AgentsPay) — FastAPI JSON-RPC server
- [AgentsPay A2A Agent Card](https://github.com/1pacent/AgentsPay) — /.well-known/agent.json
- [AgentsPay n8n Node](https://github.com/1pacent/AgentsPay) — n8n community node

## License

MIT
