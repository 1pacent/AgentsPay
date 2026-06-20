"""
Seller agent for Phase 2 simulation.

Observe: wallet balance, open RFQs in inbox, active contracts awaiting delivery,
         own reputation score, current registry listing.
Act:     PUBLISH_SERVICE, SUBMIT_QUOTE, COUNTEROFFER, SUBMIT_DELIVERABLE,
         DELEGATE_TASK (if broker), RAISE_DISPUTE.
"""

import uuid
from typing import Optional

from engine.actions import ActionType
from engine.escrow import Escrow
from engine.negotiation import NegotiationEngine, NegotiationTerms
from engine.registry import ServiceListing, ServiceRegistry
from engine.ledger import Ledger
from engine.validator import Deliverable, get_validator
from engine.wallet import AgentWallet
from simulation.agent_base import BaseAgent, SimulationContext


class SellerAgent(BaseAgent):
    def __init__(
        self,
        persona: dict,
        ledger: Ledger,
        registry: ServiceRegistry,
        negotiation_engine: NegotiationEngine,
        validator_name: str = "deterministic",
        seller_quality_map: Optional[dict] = None,
    ):
        super().__init__(persona, ledger, registry)
        self._neg_engine = negotiation_engine
        self._private = persona.get("private_state", {})
        self._validator = get_validator(validator_name, seller_quality_map)
        self._service_ids: list[str] = []
        self._active_contracts: list[str] = []
        self._published = False

    def _publish_initial_services(self, registry: ServiceRegistry) -> None:
        if self._published:
            return
        pub_state = self.persona.get("public_state", {})
        for cap_type in pub_state.get("capability_types", []):
            listing = ServiceListing(
                seller_id=self.id,
                capability_type=cap_type,
                description=f"{self.display_name} offering {cap_type}",
                price_usdc=pub_state.get("listed_price_usdc", 5.0),
                quality_guarantee=pub_state.get("advertised_quality", 0.80),
                max_concurrent_jobs=self._private.get("max_concurrent_jobs", 5),
                reputation_score=pub_state.get("reputation", 0.0),
            )
            sid = registry.publish(listing)
            self._service_ids.append(sid)
        self._published = True

    def observe(self, ctx: SimulationContext) -> str:
        self._publish_initial_services(ctx.registry)

        wallet = AgentWallet(self.id, ctx.ledger)
        msgs = ctx.bus.read(self.id)
        inbox_summary = "\n".join(
            f"  - From {m.get('from', '?')}: {m.get('type', '?')} | {m.get('summary', '')}"
            for m in msgs
        ) or "  (empty)"

        open_negs = self._neg_engine.open_for_seller(self.id)
        neg_summary = "\n".join(
            f"  - {n['negotiation_id'][:8]} from {n['buyer_id']} | status: {n['status']} | budget: ${n['max_budget_usdc']:.2f}"
            for n in open_negs
        ) or "  (none)"

        contract_summary = ""
        for cid in self._active_contracts[-3:]:
            c = ctx.ledger.get_contract(cid)
            if c:
                contract_summary += f"\n  - contract {cid[:8]}: escrow={c['escrow_status']}, delivery={c['delivery_status']}"

        # Current reputation
        pub_state = self.persona.get("public_state", {})
        current_rep = pub_state.get("reputation", 0.0)
        from engine.reputation import get_algorithm
        try:
            current_rep = get_algorithm("star_rating").score(self.id, ctx.ledger, ctx.tick)
        except Exception:
            pass

        return f"""Your wallet: ${wallet.available:.2f} available (${wallet.locked:.2f} locked)
Tick: {ctx.tick}/{ctx.total_ticks} | Reputation: {current_rep:.2f}/5.0
Listed services: {', '.join(self._service_ids) or 'none published yet'}

Inbox ({len(msgs)} messages):
{inbox_summary}

Open negotiations (you need to respond):
{neg_summary}

Active contracts:{contract_summary or ' (none)'}

What do you do next?"""

    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        action_type = action_dict.get("action_type", "")
        payload = action_dict.get("payload", {})

        if action_type == ActionType.PUBLISH_SERVICE:
            listing = ServiceListing(
                seller_id=self.id,
                capability_type=payload.get("capability_type", "general"),
                description=payload.get("description", ""),
                price_usdc=payload.get("price_usdc", 5.0),
                quality_guarantee=payload.get("quality_guarantee", 0.80),
            )
            sid = ctx.registry.publish(listing)
            self._service_ids.append(sid)
            return {"success": True, "service_id": sid}

        elif action_type == ActionType.SUBMIT_QUOTE:
            neg_id = payload.get("negotiation_id")
            if not neg_id:
                # Try to match from open negotiations
                open_negs = self._neg_engine.open_for_seller(self.id)
                if open_negs:
                    neg_id = open_negs[0]["negotiation_id"]
                else:
                    return {"success": False, "error": "no open negotiation found"}
            neg = self._neg_engine.get(neg_id)
            if not neg:
                return {"success": False, "error": "negotiation not found"}

            price = payload.get("price_usdc", self.persona.get("public_state", {}).get("listed_price_usdc", 5.0))
            min_price = self._private.get("min_acceptable_price_usdc", 1.0)

            # Enforce cost floor — seller will not go below it
            if price < min_price:
                price = min_price

            terms = NegotiationTerms(
                price_usdc=price,
                scope_description=payload.get("scope_description", "Standard delivery per listed specification"),
                delivery_tick=payload.get("delivery_tick", neg["deadline_tick"]),
                quality_guarantee=payload.get("quality_guarantee", self.persona.get("public_state", {}).get("advertised_quality", 0.80)),
            )
            ok = self._neg_engine.submit_quote(neg_id, terms)
            if ok:
                ctx.bus.send(neg["buyer_id"], {
                    "from": self.id,
                    "type": "QUOTE",
                    "negotiation_id": neg_id,
                    "summary": f"Quote: ${price:.2f} | delivery by tick {terms.delivery_tick}",
                    "terms": {"price_usdc": price, "scope": terms.scope_description, "delivery_tick": terms.delivery_tick},
                })
            return {"success": ok, "price_quoted": price}

        elif action_type == ActionType.COUNTEROFFER:
            neg_id = payload.get("negotiation_id")
            if not neg_id:
                return {"success": False, "error": "negotiation_id required"}
            neg = self._neg_engine.get(neg_id)
            if not neg:
                return {"success": False, "error": "negotiation not found"}
            price = max(
                payload.get("price_usdc", 0),
                self._private.get("min_acceptable_price_usdc", 1.0),
            )
            terms = NegotiationTerms(
                price_usdc=price,
                scope_description=payload.get("scope_description", ""),
                delivery_tick=payload.get("delivery_tick", neg["deadline_tick"]),
                quality_guarantee=payload.get("quality_guarantee", 0.80),
            )
            ok = self._neg_engine.counteroffer(neg_id, terms)
            if ok:
                ctx.bus.send(neg["buyer_id"], {
                    "from": self.id,
                    "type": "COUNTEROFFER",
                    "negotiation_id": neg_id,
                    "summary": f"Counter: ${price:.2f}",
                })
            return {"success": ok}

        elif action_type == ActionType.SUBMIT_DELIVERABLE:
            contract_id = payload.get("contract_id")
            if not contract_id:
                # Find first funded contract for this seller
                rows = ctx.ledger._conn.execute(
                    "SELECT contract_id FROM contracts WHERE seller_id = ? AND escrow_status = 'funded' AND delivery_status = 'pending'",
                    (self.id,),
                ).fetchall()
                if rows:
                    contract_id = rows[0]["contract_id"]
                else:
                    return {"success": False, "error": "no funded contract found"}

            content = payload.get("content", f"Deliverable from {self.id}: {payload.get('summary', 'work completed')}")
            contract = ctx.ledger.get_contract(contract_id)
            if not contract:
                return {"success": False, "error": "contract not found"}

            deliverable = Deliverable(
                contract_id=contract_id,
                seller_id=self.id,
                content=content,
                capability_type=contract.get("service_id", "general"),
                claimed_quality=self._private.get("true_quality_capability", 0.75),
            )
            validation = self._validator.validate(
                deliverable,
                threshold=contract.get("quality_threshold", 0.75) or 0.75,
            )

            escrow = Escrow(contract_id, ctx.ledger)
            ok = escrow.submit_deliverable(validation.score)

            if ok:
                if not contract_id in self._active_contracts:
                    self._active_contracts.append(contract_id)
                ctx.bus.send(contract["buyer_id"], {
                    "from": self.id,
                    "type": "DELIVERABLE_SUBMITTED",
                    "contract_id": contract_id,
                    "summary": f"Deliverable submitted. Validation score: {validation.score:.2f}. {validation.notes}",
                    "validation_score": validation.score,
                    "validation_passed": validation.passed,
                    "content_preview": content[:100],
                })
            return {"success": ok, "validation_score": validation.score, "passed": validation.passed}

        elif action_type == ActionType.RAISE_DISPUTE:
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
                    "summary": f"Seller disputes buyer rejection: {payload.get('reason', '')}",
                    "buyer_id": contract["buyer_id"],
                })
            return {"success": ok}

        return {"success": False, "error": f"Unhandled action: {action_type}"}
