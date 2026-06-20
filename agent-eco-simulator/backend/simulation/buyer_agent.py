"""
Buyer agent for Phase 2 simulation.

Observe: wallet balance, registry search results, active negotiations,
         inbox messages (quotes, deliverables, dispute outcomes).
Act:     SEARCH_CAPABILITY, REQUEST_QUOTE, COUNTEROFFER, ACCEPT_SCOPE,
         FUND_ESCROW, ACCEPT_DELIVERABLE, REJECT_DELIVERABLE, RAISE_DISPUTE,
         RATE_PROVIDER.
"""

import uuid
from typing import Optional

from engine.actions import ActionType
from engine.escrow import Escrow
from engine.negotiation import NegotiationEngine, NegotiationTerms
from engine.registry import ServiceRegistry
from engine.ledger import Ledger
from engine.wallet import AgentWallet
from simulation.agent_base import BaseAgent, SimulationContext


class BuyerAgent(BaseAgent):
    def __init__(self, persona: dict, ledger: Ledger, registry: ServiceRegistry, negotiation_engine: NegotiationEngine):
        super().__init__(persona, ledger, registry)
        self._neg_engine = negotiation_engine
        self._private = persona.get("private_state", {})
        self._active_contracts: list[str] = []

    def observe(self, ctx: SimulationContext) -> str:
        wallet = AgentWallet(self.id, ctx.ledger)
        msgs = ctx.bus.read(self.id)
        inbox_summary = "\n".join(
            f"  - From {m.get('from', '?')}: {m.get('type', '?')} — {m.get('summary', '')}"
            for m in msgs
        ) or "  (empty)"

        active_negs = self._neg_engine.active_for_buyer(self.id)
        neg_summary = "\n".join(
            f"  - neg {n['negotiation_id'][:8]} with {n['seller_id']} | status: {n['status']} | price: ${n.get('current_price_usdc', 'pending')}"
            for n in active_negs
        ) or "  (none)"

        contract_summary = ""
        for cid in self._active_contracts[-3:]:
            c = ctx.ledger.get_contract(cid)
            if c:
                contract_summary += f"\n  - contract {cid[:8]}: escrow={c['escrow_status']}, delivery={c['delivery_status']}, payment={c['payment_status']}"

        # Registry snapshot for the buyer's preferred capability types
        cap_types = self.persona.get("public_state", {}).get("preferred_capability_types", [])
        listings_preview = ""
        for cap in cap_types[:2]:
            results = ctx.registry.search(cap, limit=3)
            if results:
                listings_preview += f"\n  {cap}: " + ", ".join(
                    f"{s.seller_id}@${s.price_usdc} rep={s.reputation_score:.1f}" for s in results
                )

        return f"""Your wallet: ${wallet.available:.2f} available (${wallet.locked:.2f} locked in escrow)
Tick: {ctx.tick}/{ctx.total_ticks}

Inbox ({len(msgs)} messages):
{inbox_summary}

Active negotiations:
{neg_summary}

Active contracts:{contract_summary or ' (none)'}

Registry preview (your capability types):{listings_preview or ' (no listings found)'}

What do you do next?"""

    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        action_type = action_dict.get("action_type", "")
        payload = action_dict.get("payload", {})

        if action_type == ActionType.SEARCH_CAPABILITY:
            results = ctx.registry.search(
                capability_type=payload.get("capability_type", ""),
                max_price_usdc=payload.get("max_price_usdc"),
                min_quality=payload.get("min_quality"),
                min_reputation=payload.get("min_reputation"),
            )
            summary = f"Found {len(results)} providers for {payload.get('capability_type')}"
            if results:
                ctx.bus.send(self.id, {
                    "from": "registry",
                    "type": "SEARCH_RESULTS",
                    "summary": summary,
                    "results": [{"seller_id": s.seller_id, "price": s.price_usdc, "rep": s.reputation_score} for s in results],
                })
            return {"success": True, "summary": summary}

        elif action_type == ActionType.REQUEST_QUOTE:
            seller_id = payload.get("seller_id")
            service_id = payload.get("service_id", "")
            if not seller_id:
                return {"success": False, "error": "seller_id required"}
            neg_id = self._neg_engine.open_rfq(
                buyer_id=self.id,
                seller_id=seller_id,
                service_id=service_id,
                task_description=payload.get("task_description", ""),
                max_budget_usdc=payload.get("max_budget_usdc", self._private.get("max_budget_usdc", 10.0)),
                quality_threshold=payload.get("quality_threshold", self._private.get("min_quality_threshold", 0.75)),
                deadline_tick=payload.get("deadline_tick", ctx.tick + 100),
                current_tick=ctx.tick,
            )
            ctx.bus.send(seller_id, {
                "from": self.id,
                "type": "RFQ",
                "negotiation_id": neg_id,
                "summary": f"RFQ for {payload.get('task_description', '')[:60]}",
                "payload": payload,
            })
            return {"success": True, "negotiation_id": neg_id}

        elif action_type == ActionType.COUNTEROFFER:
            neg_id = payload.get("negotiation_id")
            if not neg_id:
                return {"success": False, "error": "negotiation_id required"}
            neg = self._neg_engine.get(neg_id)
            if not neg:
                return {"success": False, "error": "negotiation not found"}
            terms = NegotiationTerms(
                price_usdc=payload.get("price_usdc", 0),
                scope_description=payload.get("scope_description", ""),
                delivery_tick=payload.get("delivery_tick", neg["deadline_tick"]),
                quality_guarantee=payload.get("quality_guarantee", neg["quality_threshold"]),
            )
            ok = self._neg_engine.counteroffer(neg_id, terms)
            if ok:
                ctx.bus.send(neg["seller_id"], {
                    "from": self.id,
                    "type": "COUNTEROFFER",
                    "negotiation_id": neg_id,
                    "summary": f"Counter: ${terms.price_usdc:.2f}",
                    "terms": {"price_usdc": terms.price_usdc, "scope": terms.scope_description},
                })
            return {"success": ok}

        elif action_type == ActionType.ACCEPT_SCOPE:
            neg_id = payload.get("negotiation_id")
            if not neg_id:
                return {"success": False, "error": "negotiation_id required"}
            agreed_terms = self._neg_engine.accept(neg_id)
            if not agreed_terms:
                return {"success": False, "error": "cannot accept — invalid state or no terms"}
            neg = self._neg_engine.get(neg_id)
            contract_id = f"ctr_{uuid.uuid4().hex[:10]}"
            ctx.ledger.upsert_contract(
                contract_id,
                buyer_id=self.id,
                seller_id=neg["seller_id"],
                service_id=neg["service_id"],
                agreed_price_usdc=agreed_terms.price_usdc,
                deadline_tick=agreed_terms.delivery_tick,
                created_tick=ctx.tick,
            )
            self._active_contracts.append(contract_id)
            ctx.bus.send(neg["seller_id"], {
                "from": self.id,
                "type": "SCOPE_ACCEPTED",
                "contract_id": contract_id,
                "summary": f"Scope accepted at ${agreed_terms.price_usdc:.2f}. Please fund escrow next.",
            })
            return {"success": True, "contract_id": contract_id}

        elif action_type == ActionType.FUND_ESCROW:
            contract_id = payload.get("contract_id")
            if not contract_id:
                return {"success": False, "error": "contract_id required"}
            contract = ctx.ledger.get_contract(contract_id)
            if not contract:
                return {"success": False, "error": "contract not found"}
            escrow = Escrow(contract_id, ctx.ledger)
            buyer_wallet = AgentWallet(self.id, ctx.ledger)
            ok = escrow.fund(
                buyer_wallet=buyer_wallet,
                amount_usdc=contract["agreed_price_usdc"],
                seller_id=contract["seller_id"],
                deadline_tick=contract.get("deadline_tick", ctx.tick + 100),
            )
            if ok:
                ctx.bus.send(contract["seller_id"], {
                    "from": self.id,
                    "type": "ESCROW_FUNDED",
                    "contract_id": contract_id,
                    "summary": f"Escrow funded ${contract['agreed_price_usdc']:.2f}. Please begin work.",
                })
            return {"success": ok}

        elif action_type == ActionType.ACCEPT_DELIVERABLE:
            contract_id = payload.get("contract_id")
            if not contract_id:
                return {"success": False, "error": "contract_id required"}
            escrow = Escrow(contract_id, ctx.ledger)
            contract = ctx.ledger.get_contract(contract_id)
            seller_wallet = AgentWallet(contract["seller_id"], ctx.ledger)
            # Validate then release
            score = payload.get("quality_score", 0.8)
            escrow.validate(score)
            ok = escrow.release(seller_wallet)
            if ok:
                ctx.bus.send(contract["seller_id"], {
                    "from": self.id,
                    "type": "PAYMENT_RELEASED",
                    "contract_id": contract_id,
                    "summary": f"Deliverable accepted. Payment released. Quality score: {score:.2f}",
                })
            return {"success": ok}

        elif action_type == ActionType.REJECT_DELIVERABLE:
            contract_id = payload.get("contract_id")
            if not contract_id:
                return {"success": False, "error": "contract_id required"}
            escrow = Escrow(contract_id, ctx.ledger)
            ok = escrow.raise_dispute()
            contract = ctx.ledger.get_contract(contract_id)
            if ok and contract:
                ctx.bus.send("dispute_resolver", {
                    "from": self.id,
                    "type": "DISPUTE_RAISED",
                    "contract_id": contract_id,
                    "summary": f"Buyer rejected deliverable: {payload.get('reason', 'quality below threshold')}",
                    "seller_id": contract["seller_id"],
                })
            return {"success": ok}

        elif action_type == ActionType.RATE_PROVIDER:
            contract_id = payload.get("contract_id")
            provider_id = payload.get("provider_id")
            score = payload.get("score", 3.0)
            comment = payload.get("comment", "")
            if not (contract_id and provider_id):
                return {"success": False, "error": "contract_id and provider_id required"}
            if not (0.0 <= score <= 5.0):
                return {"success": False, "error": "score must be 0–5"}
            ctx.ledger._conn.execute(
                """INSERT OR REPLACE INTO reputation (provider_id, contract_id, score, comment, tick)
                   VALUES (?, ?, ?, ?, ?)""",
                (provider_id, contract_id, score, comment, ctx.tick),
            )
            ctx.ledger._conn.commit()
            listing = ctx.registry.get(provider_id) or next(
                (s for s in ctx.registry.all_active() if s.seller_id == provider_id), None
            )
            if listing:
                from engine.reputation import get_algorithm
                algo = get_algorithm("star_rating")
                new_rep = algo.score(provider_id, ctx.ledger, ctx.tick)
                ctx.registry.update_reputation(listing.service_id, new_rep)
            return {"success": True, "summary": f"Rated {provider_id} {score}/5"}

        return {"success": False, "error": f"Unhandled action type: {action_type}"}
