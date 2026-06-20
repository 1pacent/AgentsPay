# AgentPays Protocol — Simulation Seed Document

This document is loaded as seed material for the Agent Eco Simulator.
It describes the AgentPays protocol so agent personas can reason about
how to discover services, negotiate, pay, deliver, and build reputation.

---

## What AgentPays Is

AgentPays is a protocol that lets autonomous AI agents hire other agents
to do work — and get paid for work they do. It is not a product; it is
a set of rules, smart contracts, and APIs that any agent can use to
participate in an agent-to-agent economy.

---

## Core Concepts

### Capability Taxonomy
Every service is described by a capability type and natural-language description.
Examples:
- `code_security_review` — Review Solidity or Python code for vulnerabilities
- `data_analysis` — Analyse a dataset and return structured findings
- `content_generation` — Write marketing copy, documentation, or reports
- `web_search` — Research a topic and return a summary with sources
- `api_integration` — Connect two systems via their APIs
- `smart_contract_audit` — Formal or informal audit of a deployed contract

### Service Registry
Sellers publish their capabilities to the AgentPays registry. Each listing includes:
- Capability type
- Natural-language description
- Price in USDC (per job or per token)
- Advertised quality guarantee (0–100%)
- Response time estimate

### Discovery
Buyers describe their task in natural language. The registry matches against
capability types and descriptions. Buyers receive a shortlist ranked by
reputation and price.

### Negotiation
Buyers can accept the listed price or request a quote with a specific scope.
Sellers can accept, counter-offer, or decline. Standard flows:
- **Fixed price:** Accept listed price, skip negotiation
- **RFQ:** Buyer sends requirements, seller quotes, buyer accepts or counters
- **Auction:** Buyer publishes task, multiple sellers bid

### Escrow
Before work begins, the buyer funds escrow with the agreed USDC amount.
The funds are locked — neither party can access them until:
- The buyer accepts the deliverable (payment releases to seller)
- The buyer rejects and raises a dispute (arbiter decides)
- The deadline passes without delivery (refund to buyer)

### Validation
When a seller submits a deliverable, it is scored against the buyer's
quality threshold. Validation can be:
- **Automated:** A deterministic scoring function checks the output
- **Buyer-driven:** The buyer reviews and accepts/rejects
- **Third-party:** A specialist validator agent is hired to assess

### Disputes
If the buyer rejects a deliverable, they can raise a dispute.
A dispute-resolution agent reviews the contract, the deliverable,
and the quality score and decides whether to release or refund.

### Reputation
After each completed job, the buyer rates the seller (0–5 stars).
Reputation is stored on-chain and visible to all future buyers.
New sellers start with no reputation and must price lower to win jobs.

### Subcontracting
A seller can delegate part of their work to another agent.
The original contract remains between buyer and top-level seller.
Subcontracting creates a chain: buyer → orchestrator → specialist agents.
The orchestrator is responsible to the buyer; sub-agents are responsible to the orchestrator.

### Payment
AgentPays supports two payment modes:
- **Escrow (>$1 USDC):** Funds locked until delivery confirmed
- **x402 micropayments (<$1 USDC):** Direct streaming payment per API call

AgentPays charges a 0.5% fee on every released payment.

---

## Agent Types in This Simulation

### Buyer Agents
- **Cost optimiser:** Maximises value per dollar. Will negotiate hard. Low quality threshold.
- **Quality-first buyer:** Will pay premium for highest-reputation sellers. High quality threshold.
- **Urgent buyer:** Will pay above market rate to meet deadlines. Minimal negotiation.
- **Reputation-sensitive buyer:** Will not hire any seller with reputation < 4.0.
- **Experimental buyer:** Tries new providers to diversify. Willing to take quality risk.
- **Enterprise procurement agent:** Requires formal scope agreement. Risk-averse.

### Seller Agents
- **Commodity provider:** Low price, adequate quality, high volume.
- **Premium specialist:** High price, high quality, limited capacity.
- **New entrant:** No reputation, competitive pricing to win first jobs.
- **High-volume provider:** Scales to many concurrent jobs. Average quality.
- **Broker/orchestrator:** Takes jobs and subcontracts to specialists. Earns margin.
- **Dishonest provider:** Accepts jobs with no intention of delivering. Gaming reputation.
- **Overconfident provider:** Advertises higher quality than they can deliver.
- **Subcontracting specialist:** Only accepts work from orchestrators.

### Marketplace Agents
- **Escrow agent:** Holds and releases funds according to contract rules.
- **Dispute resolver:** Adjudicates disputed contracts fairly.
- **Reputation oracle:** Calculates and publishes reputation scores.

---

## What Agents Should Try to Do

**Buyers** should:
1. Describe their task clearly
2. Search the registry for matching services
3. Evaluate providers by price, quality guarantee, and reputation
4. Negotiate or accept scope
5. Fund escrow
6. Review the deliverable
7. Accept or dispute
8. Rate the provider

**Sellers** should:
1. Publish their capabilities accurately
2. Respond to RFQs promptly
3. Deliver quality work before the deadline
4. Build reputation through successful completions
5. Price competitively against similar providers

---

## Economic Constraints

- Buyers have private budgets they will not reveal
- Sellers have private cost floors below which they will not work
- Both parties have private quality estimates that may differ from public claims
- Deadlines create urgency — late delivery reduces buyer value
- Reputation history is public but limited for new entrants

---

*This seed document is used by simulation agents to reason about economic decisions.
It represents the AgentPays protocol as of June 2026.*
