"""
Phase 2 simulation runner — full economic engine with deterministic ledger.

Unlike Phase 1 (prompt-only narrative), this runner:
- Writes real state to the ledger on every action
- Enforces valid action transitions via the engine
- Produces trustworthy economic metrics from ledger data
- Can run scenario comparisons (e.g. fixed price vs negotiation)

Usage:
  from backend.simulation.runner import SimulationRunner
  runner = SimulationRunner.from_scenario("01_discovery")
  results = runner.run()
"""

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..engine.ledger import Ledger
from ..engine.negotiation import NegotiationEngine
from ..engine.registry import ServiceRegistry
from ..engine.wallet import AgentWallet
from ..metrics.collector import MetricsCollector
from .agent_base import MessageBus, SimulationContext
from .buyer_agent import BuyerAgent
from .marketplace_agents import (
    DisputeResolverAgent,
    EscrowMarketplaceAgent,
    ReputationOracleAgent,
)
from .seller_agent import SellerAgent

ROOT = Path(__file__).parent.parent
SCENARIOS_DIR = ROOT / "simulation" / "scenarios"
PERSONAS_DIR = ROOT / "simulation" / "personas"
RESULTS_DIR = ROOT / "simulation" / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _load_persona(persona_type: str, persona_id: str) -> dict:
    path = PERSONAS_DIR / persona_type / f"{persona_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Persona not found: {path}")
    return _load_yaml(path)


class SimulationRunner:
    def __init__(
        self,
        scenario: dict,
        db_path: Optional[str] = None,
        reputation_algorithm: str = "time_decayed",
        validator_name: str = "deterministic",
        agentpays_fee_pct: float = 0.005,
    ):
        self.scenario = scenario
        self._fee_pct = agentpays_fee_pct
        self._reputation_algorithm = reputation_algorithm

        # Core infrastructure
        db = db_path or f"/tmp/sim_{uuid.uuid4().hex[:8]}.db"
        self.ledger = Ledger(db)
        self.registry = ServiceRegistry()
        self.message_bus = MessageBus()
        self.neg_engine = NegotiationEngine(self.ledger)
        self.metrics = MetricsCollector(self.ledger)

        # Build seller quality map for deterministic validator
        self._seller_quality_map: dict[str, float] = {}

        # Agent population
        self.buyers: list[BuyerAgent] = []
        self.sellers: list[SellerAgent] = []
        self.marketplace: list = []
        self._run_log: list[dict] = []

        self._build_population(validator_name)

    @classmethod
    def from_scenario(cls, scenario_id: str, **kwargs) -> "SimulationRunner":
        path = SCENARIOS_DIR / f"{scenario_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Scenario not found: {path}")
        scenario = _load_yaml(path)
        return cls(scenario, **kwargs)

    def _build_population(self, validator_name: str) -> None:
        scenario = self.scenario

        # Buyers
        for persona_id in scenario.get("agents", {}).get("buyers", []):
            try:
                persona = _load_persona("buyers", persona_id)
                agent = BuyerAgent(persona, self.ledger, self.registry, self.neg_engine)
                # Fund wallet from private state
                initial_funds = persona.get("private_state", {}).get("max_budget_usdc", 10.0) * 1.5
                self.ledger.credit(agent.id, initial_funds)
                self.buyers.append(agent)
            except FileNotFoundError as e:
                print(f"[WARN] {e}")

        # Sellers
        for persona_id in scenario.get("agents", {}).get("sellers", []):
            try:
                persona = _load_persona("sellers", persona_id)
                true_q = persona.get("private_state", {}).get("true_quality_capability", 0.75)
                self._seller_quality_map[persona_id] = true_q
                agent = SellerAgent(
                    persona, self.ledger, self.registry, self.neg_engine,
                    validator_name=validator_name,
                    seller_quality_map=self._seller_quality_map,
                )
                # Give sellers a small float for operational costs
                self.ledger.credit(agent.id, 5.0)
                self.sellers.append(agent)
            except FileNotFoundError as e:
                print(f"[WARN] {e}")

        # Marketplace agents
        mp_ids = scenario.get("agents", {}).get("marketplace", [])
        for persona_id in mp_ids:
            try:
                persona = _load_persona("marketplace", persona_id)
                if persona_id == "escrow_agent":
                    self.marketplace.append(EscrowMarketplaceAgent(persona, self.ledger, self.registry))
                elif persona_id == "dispute_resolver":
                    self.marketplace.append(DisputeResolverAgent(persona, self.ledger, self.registry))
                elif persona_id == "reputation_oracle":
                    self.marketplace.append(ReputationOracleAgent(persona, self.ledger, self.registry, self._reputation_algorithm))
            except FileNotFoundError as e:
                print(f"[WARN] {e}")

        all_agents = len(self.buyers) + len(self.sellers) + len(self.marketplace)
        print(f"Population: {len(self.buyers)} buyers, {len(self.sellers)} sellers, {len(self.marketplace)} marketplace | {all_agents} total")

    def run(self, ticks: Optional[int] = None, verbose: bool = True) -> dict:
        total_ticks = ticks or self.scenario.get("initial_conditions", {}).get("ticks", 100)
        start_time = time.time()

        print(f"\n{'='*60}")
        print(f"SCENARIO: {self.scenario.get('name', 'Unnamed')}")
        print(f"Ticks: {total_ticks} | Agents: {len(self.buyers)}B + {len(self.sellers)}S + {len(self.marketplace)}M")
        print(f"{'='*60}")

        # Tick loop
        for tick in range(1, total_ticks + 1):
            ctx = SimulationContext(
                ledger=self.ledger,
                registry=self.registry,
                message_bus=self.message_bus,
                tick=tick,
                total_ticks=total_ticks,
            )

            tick_actions = []

            # 1. Marketplace agents first (process deadlines, disputes, reputation)
            for agent in self.marketplace:
                result = agent.step(ctx)
                tick_actions.append({"agent": agent.id, "type": "marketplace", "result": result})

            # 2. Sellers (respond to RFQs, submit deliverables)
            for agent in self.sellers:
                result = agent.step(ctx)
                if result:
                    tick_actions.append({
                        "agent": agent.id,
                        "type": "seller",
                        "action": result.get("action_type"),
                        "success": result.get("success"),
                    })

            # 3. Buyers (search, request quotes, fund escrow, accept/reject)
            for agent in self.buyers:
                result = agent.step(ctx)
                if result:
                    tick_actions.append({
                        "agent": agent.id,
                        "type": "buyer",
                        "action": result.get("action_type"),
                        "success": result.get("success"),
                    })

            self._run_log.append({"tick": tick, "actions": tick_actions})

            if verbose and tick % 10 == 0:
                snap = self.metrics.snapshot(self._fee_pct)
                print(
                    f"  Tick {tick:3d}/{total_ticks} | "
                    f"GTV: ${snap['gross_transaction_value_usdc']:.2f} | "
                    f"CR: {snap['completion_rate']:.1%} | "
                    f"Disputes: {snap['dispute_rate']:.1%} | "
                    f"AEHS: {snap['aehs']:.3f}"
                )

        elapsed = time.time() - start_time
        final_metrics = self.metrics.snapshot(self._fee_pct)

        # Per-agent summaries
        agent_summaries = [a.action_summary() for a in self.buyers + self.sellers]

        result = {
            "scenario_id": self.scenario.get("id", "unknown"),
            "scenario_name": self.scenario.get("name", ""),
            "ticks_run": total_ticks,
            "elapsed_seconds": round(elapsed, 2),
            "agents": {
                "buyers": [a.id for a in self.buyers],
                "sellers": [a.id for a in self.sellers],
                "marketplace": [a.id for a in self.marketplace],
            },
            "metrics": final_metrics,
            "agent_summaries": agent_summaries,
            "run_log": self._run_log,
            "run_at": datetime.now().isoformat(),
        }

        # Save result
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_path = RESULTS_DIR / f"{self.scenario.get('id', 'run')}_{ts}.json"
        result_path.write_text(json.dumps(result, indent=2))
        print(f"\nResults saved: {result_path}")
        print(f"Final AEHS: {final_metrics['aehs']:.3f} | GTV: ${final_metrics['gross_transaction_value_usdc']:.2f} | "
              f"Completion: {final_metrics['completion_rate']:.1%}")

        return result

    def close(self) -> None:
        self.ledger.close()


class ScenarioComparison:
    """
    Run the same scenario under multiple conditions and compare metrics side-by-side.
    Used for: fixed price vs negotiation, escrow variants, reputation algorithms.
    """

    def __init__(self, scenario_id: str, conditions: list[dict]):
        self.scenario_id = scenario_id
        self.conditions = conditions   # list of {"name": str, "kwargs": dict}

    def run(self, ticks: int = 100, verbose: bool = False) -> dict:
        results = {}
        for condition in self.conditions:
            name = condition["name"]
            kwargs = condition.get("kwargs", {})
            print(f"\n=== Condition: {name} ===")
            runner = SimulationRunner.from_scenario(self.scenario_id, **kwargs)
            result = runner.run(ticks=ticks, verbose=verbose)
            results[name] = result["metrics"]
            runner.close()

        comparison = {
            "scenario_id": self.scenario_id,
            "conditions": list(results.keys()),
            "metrics_by_condition": results,
            "winner": self._find_winner(results),
        }

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = RESULTS_DIR / f"comparison_{self.scenario_id}_{ts}.json"
        path.write_text(json.dumps(comparison, indent=2))
        print(f"\nComparison saved: {path}")
        return comparison

    def _find_winner(self, results: dict) -> dict:
        if not results:
            return {}
        best_aehs = max(results.items(), key=lambda x: x[1].get("aehs", 0))
        best_gtv = max(results.items(), key=lambda x: x[1].get("gross_transaction_value_usdc", 0))
        best_cr = max(results.items(), key=lambda x: x[1].get("completion_rate", 0))
        return {
            "highest_aehs": best_aehs[0],
            "highest_gtv": best_gtv[0],
            "highest_completion_rate": best_cr[0],
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgentPays Phase 2 Simulation Runner")
    parser.add_argument("scenario", help="Scenario ID (e.g. 01_discovery)")
    parser.add_argument("--ticks", type=int, default=None)
    parser.add_argument("--fee-pct", type=float, default=0.005)
    parser.add_argument("--reputation", default="time_decayed",
                        choices=["star_rating", "completion_rate", "time_decayed", "verified_delivery"])
    parser.add_argument("--validator", default="deterministic",
                        choices=["deterministic", "length_heuristic", "always_pass", "always_fail"])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    runner = SimulationRunner.from_scenario(
        args.scenario,
        agentpays_fee_pct=args.fee_pct,
        reputation_algorithm=args.reputation,
        validator_name=args.validator,
    )
    runner.run(ticks=args.ticks, verbose=not args.quiet)
    runner.close()
