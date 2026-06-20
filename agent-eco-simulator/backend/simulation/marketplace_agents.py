"""
Marketplace agents — escrow, dispute resolver, reputation oracle.

These are deterministic-first: they run rule-based logic before
optionally calling an LLM for complex dispute reasoning.
"""

from ..engine.escrow import Escrow, EscrowStatus
from ..engine.ledger import Ledger
from ..engine.registry import ServiceRegistry
from ..engine.reputation import get_algorithm
from ..engine.wallet import AgentWallet
from .agent_base import BaseAgent, SimulationContext


class EscrowMarketplaceAgent(BaseAgent):
    """Deterministic escrow processor. No LLM calls — pure state machine."""

    def observe(self, ctx: SimulationContext) -> str:
        return "(Escrow agent observes funded contracts awaiting state transitions)"

    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        return {"success": True, "note": "Escrow transitions handled inline by buyer/seller agents"}

    def step(self, ctx: SimulationContext) -> dict:
        # Check for expired contracts (deadline exceeded, still funded)
        expired = ctx.ledger._conn.execute(
            """SELECT contract_id, buyer_id, agreed_price_usdc
               FROM contracts
               WHERE escrow_status = 'funded'
               AND deadline_tick IS NOT NULL
               AND deadline_tick < ?""",
            (ctx.tick,),
        ).fetchall()
        refunded = 0
        for row in expired:
            cid = row["contract_id"]
            escrow = Escrow(cid, ctx.ledger)
            buyer_wallet = AgentWallet(row["buyer_id"], ctx.ledger)
            if escrow.refund(buyer_wallet):
                ctx.bus.send(row["buyer_id"], {
                    "from": "escrow_agent",
                    "type": "DEADLINE_REFUND",
                    "contract_id": cid,
                    "summary": f"Deadline passed. ${row['agreed_price_usdc']:.2f} refunded.",
                })
                refunded += 1
        return {"success": True, "deadline_refunds": refunded}


class DisputeResolverAgent(BaseAgent):
    """Resolves disputes using validation scores + configurable rules."""

    def observe(self, ctx: SimulationContext) -> str:
        disputed = ctx.ledger._conn.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE escrow_status = 'disputed'"
        ).fetchone()["n"]
        return f"(Dispute resolver: {disputed} contracts in dispute)"

    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        return {"success": True}

    def step(self, ctx: SimulationContext) -> dict:
        msgs = ctx.bus.read(self.id)
        resolved = 0
        for msg in msgs:
            if msg.get("type") != "DISPUTE_RAISED":
                continue
            contract_id = msg.get("contract_id")
            if not contract_id:
                continue
            contract = ctx.ledger.get_contract(contract_id)
            if not contract:
                continue

            score = contract.get("validation_score")
            quality_threshold = 0.75  # default; in Phase 3 read from contract

            escrow = Escrow(contract_id, ctx.ledger)
            buyer_wallet = AgentWallet(contract["buyer_id"], ctx.ledger)
            seller_wallet = AgentWallet(contract["seller_id"], ctx.ledger)

            if score is not None and score >= quality_threshold:
                # Deliverable meets standard — release to seller
                escrow.release(seller_wallet)
                decision = f"RELEASE to seller. Score {score:.2f} >= threshold {quality_threshold:.2f}"
                ctx.bus.send(contract["buyer_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})
                ctx.bus.send(contract["seller_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})
            elif score is not None and score < quality_threshold * 0.7:
                # Clearly failed — refund buyer
                escrow.refund(buyer_wallet)
                decision = f"REFUND to buyer. Score {score:.2f} far below threshold."
                ctx.bus.send(contract["buyer_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})
                ctx.bus.send(contract["seller_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})
            else:
                # Ambiguous — partial: 60% seller, 40% buyer refund
                amount = contract.get("agreed_price_usdc", 0)
                seller_share = round(amount * 0.60, 4)
                buyer_refund = round(amount * 0.40, 4)
                ctx.ledger.credit(contract["seller_id"], seller_share)
                ctx.ledger.credit(contract["buyer_id"], buyer_refund)
                ctx.ledger.upsert_contract(contract_id, payment_status="partial", escrow_status=EscrowStatus.RELEASED)
                decision = f"PARTIAL: seller gets ${seller_share:.2f}, buyer refunded ${buyer_refund:.2f}."
                ctx.bus.send(contract["buyer_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})
                ctx.bus.send(contract["seller_id"], {"from": "dispute_resolver", "type": "DISPUTE_RESOLVED", "contract_id": contract_id, "summary": decision})

            resolved += 1

        return {"success": True, "disputes_resolved": resolved}


class ReputationOracleAgent(BaseAgent):
    """Recalculates reputation scores and detects Sybil patterns."""

    def __init__(self, persona: dict, ledger: Ledger, registry: ServiceRegistry, algorithm: str = "time_decayed"):
        super().__init__(persona, ledger, registry)
        self._algorithm_name = algorithm
        self._algo = get_algorithm(algorithm)
        self._flagged_accounts: set[str] = set()

    def observe(self, ctx: SimulationContext) -> str:
        return f"(Reputation oracle: algorithm={self._algorithm_name}, flagged={len(self._flagged_accounts)})"

    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        return {"success": True}

    def step(self, ctx: SimulationContext) -> dict:
        self._detect_sybil(ctx)
        self._recalculate_scores(ctx)
        return {"success": True, "flagged_accounts": len(self._flagged_accounts)}

    def _recalculate_scores(self, ctx: SimulationContext) -> None:
        sellers = ctx.ledger._conn.execute(
            "SELECT DISTINCT provider_id FROM reputation"
        ).fetchall()
        for row in sellers:
            provider_id = row["provider_id"]
            score = self._algo.score(provider_id, ctx.ledger, ctx.tick)
            # Update all active listings for this seller
            for listing in ctx.registry.all_active():
                if listing.seller_id == provider_id:
                    ctx.registry.update_reputation(listing.service_id, score)

    def _detect_sybil(self, ctx: SimulationContext) -> None:
        # Rule 1: Buyer accounts with zero purchase history submitting ratings
        raters = ctx.ledger._conn.execute(
            "SELECT DISTINCT provider_id, contract_id FROM reputation"
        ).fetchall()
        for row in raters:
            contract = ctx.ledger.get_contract(row["contract_id"])
            if not contract:
                # Rating without a valid contract — Sybil signal
                rater_rows = ctx.ledger._conn.execute(
                    "SELECT buyer_id FROM contracts WHERE contract_id = ?", (row["contract_id"],)
                ).fetchall()
                for r in rater_rows:
                    self._flagged_accounts.add(r["buyer_id"])
                    ctx.bus.send("dispute_resolver", {
                        "from": "reputation_oracle",
                        "type": "SYBIL_ALERT",
                        "summary": f"Rating submitted without valid contract by buyer — flagging",
                        "contract_id": row["contract_id"],
                    })

        # Rule 2: Buyer accounts that exclusively rate one seller 5/5
        buyers = ctx.ledger._conn.execute(
            """SELECT r.contract_id, c.buyer_id, r.provider_id, r.score
               FROM reputation r
               JOIN contracts c ON r.contract_id = c.contract_id
               WHERE c.buyer_id NOT IN ({})""".format(
                ",".join("?" * len(self._flagged_accounts)) if self._flagged_accounts else "'_none_'"
            ),
            list(self._flagged_accounts) if self._flagged_accounts else [],
        ).fetchall()

        buyer_ratings: dict[str, dict] = {}
        for row in buyers:
            bid = row["buyer_id"]
            buyer_ratings.setdefault(bid, {"providers": set(), "scores": []})
            buyer_ratings[bid]["providers"].add(row["provider_id"])
            buyer_ratings[bid]["scores"].append(row["score"])

        for bid, data in buyer_ratings.items():
            if len(data["providers"]) == 1 and all(s == 5.0 for s in data["scores"]) and len(data["scores"]) >= 2:
                self._flagged_accounts.add(bid)
