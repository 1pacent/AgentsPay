"""
Base agent class for Phase 2 simulation.

Each agent has a three-step loop per tick:
  1. observe()  — build a view of current market state
  2. decide()   — call LLM with persona + observation → structured action JSON
  3. act()      — parse action, validate, execute against the engine

The LLM controls WHAT to do and WHAT to say.
The engine controls WHAT ACTUALLY HAPPENED.

Action format agents must output:
  <<ACTION>>
  {"action_type": "REQUEST_QUOTE", "payload": {...}}
  <</ACTION>>
  Optional narrative follows.
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

import anthropic

from engine.actions import ActionType, EconomicAction
from engine.ledger import Ledger
from engine.registry import ServiceRegistry
from engine.wallet import AgentWallet

ACTION_PATTERN = re.compile(r"<<ACTION>>\s*(\{.*?\})\s*<</ACTION>>", re.DOTALL)
CLIENT = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
MODEL = os.environ.get("SIM_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = 600


class MessageBus:
    """Simple in-memory message routing between agents."""

    def __init__(self):
        self._inbox: dict[str, list[dict]] = {}

    def send(self, to_agent_id: str, message: dict) -> None:
        self._inbox.setdefault(to_agent_id, []).append(message)

    def read(self, agent_id: str) -> list[dict]:
        msgs = self._inbox.pop(agent_id, [])
        return msgs

    def broadcast(self, message: dict, recipient_ids: list[str]) -> None:
        for agent_id in recipient_ids:
            self.send(agent_id, message)


class SimulationContext:
    """Shared state passed to every agent on each tick."""

    def __init__(
        self,
        ledger: Ledger,
        registry: ServiceRegistry,
        message_bus: MessageBus,
        tick: int,
        total_ticks: int,
    ):
        self.ledger = ledger
        self.registry = registry
        self.bus = message_bus
        self.tick = tick
        self.total_ticks = total_ticks


class BaseAgent(ABC):
    def __init__(self, persona: dict, ledger: Ledger, registry: ServiceRegistry):
        self.id = persona["id"]
        self.display_name = persona["display_name"]
        self.type = persona["type"]
        self.persona = persona
        self._ledger = ledger
        self._registry = registry
        self._history: list[dict] = []
        self._action_log: list[dict] = []
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        from seed_documents import load_seed
        seed = load_seed()
        p = self.persona
        return f"""
=== AGENTPAYS MARKETPLACE PROTOCOL ===
{seed}

=== YOUR PERSONA ===
Name: {p['display_name']}
Type: {p['type']}

{p['system_prompt']}

=== ACTION FORMAT (REQUIRED) ===
Every response MUST contain exactly one action block:

<<ACTION>>
{{"action_type": "ACTION_NAME", "payload": {{...}}}}
<</ACTION>>

Valid action types: {', '.join(t.value for t in ActionType)}

After the action block, add 1-2 sentences of reasoning.
Do NOT invent transaction outcomes — only declare your intended action.
The simulation engine decides what actually happens.
""".strip()

    def step(self, ctx: SimulationContext) -> Optional[dict]:
        observation = self.observe(ctx)
        response_text = self._llm_call(observation, ctx.tick)
        action_dict = self._parse_action(response_text)
        result = None
        if action_dict:
            result = self.act(action_dict, ctx)
            self._action_log.append({
                "tick": ctx.tick,
                "action_type": action_dict.get("action_type"),
                "payload": action_dict.get("payload", {}),
                "success": result.get("success") if result else False,
                "narrative": response_text,
            })
        self._history.append({"role": "assistant", "content": response_text})
        if len(self._history) > 16:
            self._history = self._history[-16:]
        return result

    def _llm_call(self, observation: str, tick: int) -> str:
        messages = self._history + [{"role": "user", "content": f"[TICK {tick}]\n{observation}"}]
        try:
            resp = CLIENT.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self._system_prompt,
                messages=messages,
            )
            text = resp.content[0].text
            self._history.append({"role": "user", "content": f"[TICK {tick}]\n{observation}"})
            return text
        except Exception as e:
            return f"<<ACTION>>\n{{\"action_type\": \"SEARCH_CAPABILITY\", \"payload\": {{\"capability_type\": \"data_analysis\"}}}}\n<</ACTION>>\nAPI error: {e}"

    def _parse_action(self, text: str) -> Optional[dict]:
        match = ACTION_PATTERN.search(text)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def wallet(self) -> AgentWallet:
        return AgentWallet(self.id, self._ledger)

    def action_summary(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self._action_log:
            a = entry.get("action_type", "unknown")
            counts[a] = counts.get(a, 0) + 1
        return {"agent_id": self.id, "type": self.type, "action_counts": counts, "total_steps": len(self._action_log)}

    @abstractmethod
    def observe(self, ctx: SimulationContext) -> str:
        """Build natural-language observation of current market state."""

    @abstractmethod
    def act(self, action_dict: dict, ctx: SimulationContext) -> dict:
        """Execute the parsed action against the engine. Return result dict."""
