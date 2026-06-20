"""
Phase 1 simulation runner — prompt-only experiment.

Loads AgentPays seed material + persona definitions + a scenario config,
then orchestrates a multi-agent conversation using the Anthropic API.

IMPORTANT: Phase 1 is QUALITATIVE only. Balances and transactions exist
as LLM-generated narrative. Do not trust economic numbers from this phase.
Use it to surface protocol design risks and emergent behaviours.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import yaml

ROOT = Path(__file__).parent.parent
PERSONAS_DIR = ROOT / "simulation" / "personas"
SCENARIOS_DIR = ROOT / "simulation" / "scenarios"
SEED_DIR = ROOT / "seed_documents"
FINDINGS_DIR = ROOT / "simulation" / "findings"
FINDINGS_DIR.mkdir(exist_ok=True)

MODEL = "claude-haiku-4-5-20251001"   # fast + cheap for bulk simulation runs
MAX_TOKENS = 800
ROUND_PAUSE_SECONDS = 0.5


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_seed_document(name: str = "agentpays_protocol.md") -> str:
    path = SEED_DIR / name
    return path.read_text()


def load_persona(persona_type: str, persona_id: str) -> dict:
    path = PERSONAS_DIR / persona_type / f"{persona_id}.yaml"
    return load_yaml(path)


def build_system_prompt(persona: dict, seed_doc: str) -> str:
    return f"""
=== AGENTPAYS MARKETPLACE PROTOCOL ===
{seed_doc}

=== YOUR PERSONA ===
Name: {persona['display_name']}
Type: {persona['type']}

{persona['system_prompt']}

=== SIMULATION RULES ===
- This is a prompt-only Phase 1 simulation. There is no real blockchain or real money.
- Narrate your actions as if they were real — be specific about amounts, service names, and decisions.
- When you take an action, prefix it with the action type in brackets, e.g.:
  [SEARCH_CAPABILITY] I am searching for providers offering smart_contract_audit...
  [REQUEST_QUOTE] I am sending an RFQ to premium_specialist for $X...
  [ACCEPT_SCOPE] I am accepting the quote from commodity_provider at $1.50...
- After each action, briefly explain your reasoning (1-2 sentences).
- Stay true to your private constraints — do not reveal budget limits or cost floors.
- Respond only as your persona. Do not break character.
""".strip()


def run_round(
    client: anthropic.Anthropic,
    agent_id: str,
    system_prompt: str,
    conversation_history: list[dict],
    scenario_context: str,
    tick: int,
) -> str:
    messages = conversation_history + [
        {
            "role": "user",
            "content": f"[TICK {tick}] {scenario_context}\n\nWhat do you do next?",
        }
    ]
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )
    return response.content[0].text


def extract_actions(text: str) -> list[str]:
    """Pull bracketed action types from agent output for logging."""
    import re
    return re.findall(r"\[([A-Z_]+)\]", text)


def run_scenario(scenario_id: str, max_rounds: int | None = None) -> dict:
    scenario_path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not scenario_path.exists():
        print(f"Scenario not found: {scenario_path}")
        sys.exit(1)

    scenario = load_yaml(scenario_path)
    seed_doc = load_seed_document()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    rounds = max_rounds or scenario.get("rounds", 20)
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario['name']}")
    print(f"Phase: {scenario['phase']} | Rounds: {rounds}")
    print(f"{'='*60}")
    print(f"Question: {scenario['test_question'].strip()}")
    print(f"Hypothesis: {scenario['hypothesis'].strip()}\n")

    # Load active agent personas from scenario
    active_agents: list[dict] = []
    for persona_type, persona_ids in scenario.get("agents", {}).items():
        if isinstance(persona_ids, list):
            for persona_id in persona_ids:
                try:
                    persona = load_persona(persona_type, persona_id)
                    active_agents.append(persona)
                except FileNotFoundError:
                    print(f"  [WARN] Persona not found: {persona_type}/{persona_id}")
        elif isinstance(persona_ids, dict):
            # nested structure (e.g. sub_agents in scenario 03)
            for _, ids in persona_ids.items():
                if isinstance(ids, list):
                    for persona_id in ids:
                        try:
                            persona = load_persona("sellers", persona_id)
                            active_agents.append(persona)
                        except FileNotFoundError:
                            print(f"  [WARN] Persona not found: sellers/{persona_id}")

    print(f"Active agents: {[a['id'] for a in active_agents]}\n")

    # Build per-agent state
    agent_states: dict[str, dict] = {}
    for agent in active_agents:
        agent_states[agent["id"]] = {
            "persona": agent,
            "system_prompt": build_system_prompt(agent, seed_doc),
            "history": [],
        }

    # Simulation log
    log: list[dict] = []
    action_counts: dict[str, int] = {}

    scenario_context = (
        f"Scenario: {scenario['name']}. "
        f"Market has {len([a for a in active_agents if a['type'] == 'buyer'])} buyers "
        f"and {len([a for a in active_agents if a['type'] == 'seller'])} sellers. "
        f"Test question: {scenario['test_question'].strip()}"
    )

    for tick in range(1, rounds + 1):
        print(f"--- Tick {tick}/{rounds} ---")

        for agent in active_agents:
            agent_id = agent["id"]
            state = agent_states[agent_id]

            try:
                response_text = run_round(
                    client=client,
                    agent_id=agent_id,
                    system_prompt=state["system_prompt"],
                    conversation_history=state["history"],
                    scenario_context=scenario_context,
                    tick=tick,
                )
            except Exception as e:
                print(f"  [{agent_id}] API error: {e}")
                continue

            actions = extract_actions(response_text)
            for a in actions:
                action_counts[a] = action_counts.get(a, 0) + 1

            # Append to this agent's conversation history
            state["history"].append({"role": "user", "content": f"[TICK {tick}] {scenario_context}\n\nWhat do you do next?"})
            state["history"].append({"role": "assistant", "content": response_text})

            # Keep history bounded to last 10 exchanges to avoid context overflow
            if len(state["history"]) > 20:
                state["history"] = state["history"][-20:]

            log.append({
                "tick": tick,
                "agent_id": agent_id,
                "agent_type": agent["type"],
                "actions": actions,
                "response": response_text,
            })

            print(f"  [{agent['display_name']}] Actions: {actions or ['(none tagged)']}")
            time.sleep(ROUND_PAUSE_SECONDS)

    # Save findings
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    findings_path = FINDINGS_DIR / f"{scenario_id}_{timestamp}.json"
    result = {
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "test_question": scenario["test_question"],
        "hypothesis": scenario.get("hypothesis", ""),
        "rounds_run": rounds,
        "agents": [a["id"] for a in active_agents],
        "action_counts": action_counts,
        "log": log,
        "run_at": timestamp,
    }
    findings_path.write_text(json.dumps(result, indent=2))
    print(f"\nFindings saved: {findings_path}")
    print(f"Action distribution: {json.dumps(action_counts, indent=2)}")

    return result


def summarise_findings(findings: dict) -> str:
    """
    Post-run: ask Claude to summarise protocol risks from the simulation log.
    Returns a markdown findings summary.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    log_excerpt = findings["log"][:30]  # first 30 events for context

    prompt = f"""You are analysing a Phase 1 prompt-only simulation of the AgentPays protocol.

Scenario: {findings['scenario_name']}
Test question: {findings['test_question']}
Hypothesis: {findings['hypothesis']}
Rounds run: {findings['rounds_run']}
Agents: {findings['agents']}
Action distribution: {json.dumps(findings['action_counts'], indent=2)}

Simulation log (first 30 entries):
{json.dumps(log_excerpt, indent=2)}

Based on this simulation, please provide:
1. **Key observations** — what emergent behaviours appeared?
2. **Protocol design risks** — what incentive misalignments or gaps were revealed?
3. **Surprising findings** — anything unexpected?
4. **Where LLMs fabricated economic facts** — instances where agents invented balances or transactions
5. **Recommendations** — specific changes to the AgentPays protocol based on what you observed

Format as markdown. Be specific and actionable. This is a pre-Phase-2 design input."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AgentPays Phase 1 Simulation Runner")
    parser.add_argument("scenario", help="Scenario ID (e.g. 01_discovery)")
    parser.add_argument("--rounds", type=int, default=None, help="Override number of rounds")
    parser.add_argument("--summarise", action="store_true", help="Auto-generate findings summary after run")
    args = parser.parse_args()

    findings = run_scenario(args.scenario, max_rounds=args.rounds)

    if args.summarise:
        print("\nGenerating findings summary...")
        summary = summarise_findings(findings)
        timestamp = findings["run_at"]
        summary_path = FINDINGS_DIR / f"{args.scenario}_{timestamp}_summary.md"
        summary_path.write_text(summary)
        print(f"\nSummary saved: {summary_path}")
        print(f"\n{summary}")
