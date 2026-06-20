"""
Post-simulation report generator.

Reads from the deterministic ledger and produces:
- Markdown narrative report
- JSON metrics export
- Scenario comparison table

All numbers derive from ledger data, never from LLM output.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from engine.ledger import Ledger
from metrics.collector import MetricsCollector


class ReportGenerator:
    def __init__(self, ledger: Ledger, fee_pct: float = 0.005):
        self._ledger = ledger
        self._metrics = MetricsCollector(ledger)
        self._fee_pct = fee_pct

    def generate(
        self,
        scenario_name: str,
        ticks_run: int,
        agent_summaries: Optional[list[dict]] = None,
        run_log: Optional[list[dict]] = None,
    ) -> str:
        snap = self._metrics.snapshot(self._fee_pct)
        agent_summaries = agent_summaries or []
        run_log = run_log or []

        # Action distribution across all agents
        all_action_counts: dict[str, int] = {}
        for summary in agent_summaries:
            for action, count in summary.get("action_counts", {}).items():
                all_action_counts[action] = all_action_counts.get(action, 0) + count

        # Top buyers and sellers by contracts
        buyer_contracts = self._ledger._conn.execute(
            "SELECT buyer_id, COUNT(*) as n, SUM(agreed_price_usdc) as total FROM contracts GROUP BY buyer_id ORDER BY total DESC LIMIT 5"
        ).fetchall()
        seller_contracts = self._ledger._conn.execute(
            "SELECT seller_id, COUNT(*) as n, SUM(agreed_price_usdc) as total, AVG(validation_score) as avg_quality FROM contracts WHERE payment_status='released' GROUP BY seller_id ORDER BY total DESC LIMIT 5"
        ).fetchall()

        # Price formation
        price_stats = self._ledger._conn.execute(
            "SELECT MIN(agreed_price_usdc) as min_p, MAX(agreed_price_usdc) as max_p, AVG(agreed_price_usdc) as avg_p FROM contracts WHERE agreed_price_usdc IS NOT NULL"
        ).fetchone()

        # Dispute breakdown
        dispute_count = self._ledger._conn.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE escrow_status='disputed'"
        ).fetchone()["n"]
        refund_count = self._ledger._conn.execute(
            "SELECT COUNT(*) as n FROM contracts WHERE payment_status='refunded'"
        ).fetchone()["n"]

        report = f"""# Agent Eco Simulator — Simulation Report

**Scenario:** {scenario_name}
**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Ticks run:** {ticks_run}

---

## Executive Metrics

| Metric | Value |
|--------|-------|
| Gross Transaction Value | ${snap['gross_transaction_value_usdc']:.4f} USDC |
| AgentPays Fee Revenue ({self._fee_pct*100:.1f}%) | ${snap['agentpays_fee_revenue_usdc']:.4f} USDC |
| Completion Rate | {snap['completion_rate']:.1%} |
| Dispute Rate | {snap['dispute_rate']:.1%} |
| Average Quality Score | {snap['average_quality']:.3f} |
| Median Negotiation Rounds | {snap['median_negotiation_rounds']:.1f} |
| Seller Concentration (HHI) | {snap['seller_concentration_hhi']:.3f} |
| Buyer Concentration (HHI) | {snap['buyer_concentration_hhi']:.3f} |
| **Agent Economy Health Score** | **{snap['aehs']:.4f}** |

---

## Price Formation

"""
        if price_stats and price_stats["avg_p"]:
            report += f"""- Min price: ${price_stats['min_p']:.4f}
- Max price: ${price_stats['max_p']:.4f}
- Average price: ${price_stats['avg_p']:.4f}

"""
        else:
            report += "_No completed contracts to analyse._\n\n"

        report += f"""---

## Action Distribution

Total actions across all agents:

"""
        if all_action_counts:
            total_actions = sum(all_action_counts.values())
            for action, count in sorted(all_action_counts.items(), key=lambda x: -x[1]):
                pct = count / total_actions * 100
                report += f"- `{action}`: {count} ({pct:.1f}%)\n"
        else:
            report += "_No actions recorded._\n"

        report += f"""
---

## Top Buyers by Spend

"""
        if buyer_contracts:
            report += "| Buyer | Contracts | Total Spent (USDC) |\n|-------|-----------|--------------------|\n"
            for row in buyer_contracts:
                report += f"| {row['buyer_id']} | {row['n']} | ${row['total'] or 0:.4f} |\n"
        else:
            report += "_No buyer data._\n"

        report += f"""
---

## Top Sellers by Revenue

"""
        if seller_contracts:
            report += "| Seller | Jobs | Revenue (USDC) | Avg Quality |\n|--------|------|----------------|-------------|\n"
            for row in seller_contracts:
                report += f"| {row['seller_id']} | {row['n']} | ${row['total'] or 0:.4f} | {row['avg_quality'] or 0:.3f} |\n"
        else:
            report += "_No seller data._\n"

        report += f"""
---

## Dispute & Refund Summary

- Contracts disputed: {dispute_count}
- Contracts refunded: {refund_count}
- Dispute rate: {snap['dispute_rate']:.1%}

"""
        report += f"""---

## Market Structure

- Seller HHI: {snap['seller_concentration_hhi']:.3f} {'(concentrated)' if snap['seller_concentration_hhi'] > 0.25 else '(competitive)'}
- Buyer HHI: {snap['buyer_concentration_hhi']:.3f} {'(concentrated)' if snap['buyer_concentration_hhi'] > 0.25 else '(competitive)'}

---

## Agent Economy Health Score Breakdown

AEHS = w(completion) + w(quality) - w(disputes) = **{snap['aehs']:.4f}**

- Completion rate contribution: {snap['completion_rate'] * 0.20:.4f}
- Quality contribution: {snap['average_quality'] * 0.15:.4f}
- Dispute penalty: {snap['dispute_rate'] * 0.10:.4f}

---

*Generated by Agent Eco Simulator. All metrics derived from deterministic ledger.*
"""
        return report

    def export_json(self, scenario_name: str, ticks_run: int, **extra) -> dict:
        snap = self._metrics.snapshot(self._fee_pct)
        snap.update({
            "scenario_name": scenario_name,
            "ticks_run": ticks_run,
            "generated_at": datetime.now().isoformat(),
            **extra,
        })
        return snap


def compare_scenarios(results: list[dict], output_path: Optional[Path] = None) -> str:
    """Render a markdown comparison table from multiple run results."""
    if not results:
        return "_No results to compare._"

    keys = ["completion_rate", "dispute_rate", "average_quality",
            "gross_transaction_value_usdc", "agentpays_fee_revenue_usdc", "aehs"]

    header = "| Metric | " + " | ".join(r.get("scenario_name", f"Run {i+1}") for i, r in enumerate(results)) + " |"
    sep = "|--------|" + "|".join("--------" for _ in results) + "|"
    rows = [header, sep]

    for key in keys:
        label = key.replace("_", " ").title()
        values = []
        for r in results:
            v = r.get("metrics", r).get(key, 0)
            if isinstance(v, float):
                if key in ("completion_rate", "dispute_rate"):
                    values.append(f"{v:.1%}")
                else:
                    values.append(f"{v:.4f}")
            else:
                values.append(str(v))
        rows.append(f"| {label} | " + " | ".join(values) + " |")

    table = "\n".join(rows)
    if output_path:
        output_path.write_text(f"# Scenario Comparison\n\n{table}\n")
    return table
