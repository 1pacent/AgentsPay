"""x402 Bazaar integration — client, config, discovery, and payment.

Wraps the x402 Bazaar API for agent service discovery and payment.
Follows the same pattern as the existing app modules.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

# ─── Exceptions ──────────────────────────────────────


class X402Error(Exception):
    """Base x402 error."""
    pass


class X402PaymentRequired(X402Error):
    """Server responded 402 — payment required."""
    def __init__(self, charge_id: str, message: str = "Payment required"):
        self.charge_id = charge_id
        super().__init__(f"{message}: charge_id={charge_id}")


# ─── Configuration ────────────────────────────────────

# Track C capability taxonomy (from agentpays-index)
CAPABILITY_TAXONOMY = {
    "data": ["analytics", "storage", "query", "etl", "visualization"],
    "ai": ["llm", "embedding", "classification", "generation", "summarization"],
    "finance": ["payment", "accounting", "invoicing", "valuation", "trading"],
    "communication": ["messaging", "email", "notification", "voice", "calendar"],
    "commerce": ["marketplace", "checkout", "shipping", "inventory", "catalog"],
    "developer": ["hosting", "ci-cd", "monitoring", "database", "auth"],
    "productivity": ["scheduling", "todo", "notes", "workflow", "forms"],
    "content": ["writing", "image", "video", "audio", "translation"],
    "research": ["search", "web-scraping", "knowledge-graph", "citation"],
    "blockchain": ["smart-contract", "defi", "nft", "wallet", "identity"],
}


@dataclass
class X402Settings:
    """x402 Bazaar configuration loaded from env vars."""
    bazaar_mcp_url: str = field(
        default_factory=lambda: os.getenv(
            "X402_BAZAAR_MCP_URL",
            "https://api.cdp.coinbase.com/v2/x402/discovery"
        )
    )
    bazaar_http_url: str = field(
        default_factory=lambda: os.getenv(
            "X402_BAZAAR_HTTP_URL",
            "https://api.cdp.coinbase.com/v2/x402/discovery"
        )
    )
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("X402_API_KEY", None)
    )
    escrow_contract: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENTPAYS_ESCROW_CONTRACT", None)
    )
    base_rpc_url: str = field(
        default_factory=lambda: os.getenv(
            "BASE_SEPOLIA_RPC_URL",
            "https://sepolia.base.org"
        )
    )
    payment_wallet_key: Optional[str] = field(
        default_factory=lambda: os.getenv("PAYMENT_WALLET_PRIVATE_KEY", None)
    )
    timeout: int = 30
    poll_interval: int = 2
    poll_max_attempts: int = 30


_x402_settings: Optional[X402Settings] = None


def get_x402_settings() -> X402Settings:
    global _x402_settings
    if _x402_settings is None:
        _x402_settings = X402Settings()
    return _x402_settings


# ─── HTTP Client ──────────────────────────────────────


class X402Client:
    """Minimal HTTP client for x402 Bazaar — stdlib only."""

    def __init__(self, settings: Optional[X402Settings] = None):
        self.settings = settings or get_x402_settings()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.api_key:
            h["Authorization"] = f"Bearer {self.settings.api_key}"
        return h

    def _request(self, url: str, method: str = "GET",
                 body: Optional[dict] = None) -> dict:
        headers = self._headers()
        data = json.dumps(body).encode() if body else None
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.settings.timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code == 402:
                err_body = json.loads(e.read().decode())
                raise X402PaymentRequired(
                    charge_id=err_body.get("charge_id", ""),
                    message=err_body.get("message", "Payment required"),
                )
            raise X402Error(f"HTTP {e.code}: {e.read().decode()}")
        except URLError as e:
            raise X402Error(f"Request failed: {e.reason}")

    def discover_mcp(self) -> list[dict]:
        """Query x402 Bazaar MCP discovery endpoint."""
        url = f"{self.settings.bazaar_mcp_url}/mcp"
        result = self._request(url)
        return result.get("services", result if isinstance(result, list) else [])

    def search(self, query: str) -> list[dict]:
        """Search x402 Bazaar by capability description."""
        from urllib.parse import quote
        url = f"{self.settings.bazaar_http_url}/search?q={quote(query)}"
        result = self._request(url)
        return result.get("results", result if isinstance(result, list) else [])

    def request_charge(self, service_id: str, amount: str) -> dict:
        """Request a payment charge from the Bazaar."""
        url = f"{self.settings.bazaar_http_url}/charge"
        body = {"service_id": service_id, "amount": amount, "currency": "USDC"}
        try:
            return self._request(url, method="POST", body=body)
        except X402PaymentRequired as e:
            return {"charge_id": e.charge_id, "service_id": service_id, "amount": amount}

    def check_charge(self, charge_id: str) -> dict:
        """Check payment charge status."""
        url = f"{self.settings.bazaar_http_url}/charge/{charge_id}"
        return self._request(url)

    def wait_for_payment(self, charge_id: str) -> dict:
        """Poll until payment is confirmed or timeout."""
        for _ in range(self.settings.poll_max_attempts):
            status = self.check_charge(charge_id)
            if status.get("status") == "confirmed":
                return status
            time.sleep(self.settings.poll_interval)
        raise X402Error(f"Payment {charge_id} not confirmed within timeout")


# ─── Taxonomy Layer ────────────────────────────────────


def classify_service(service: dict) -> list[str]:
    """Assign Track C capability categories based on description/tags.

    Uses keyword matching — no LLM cost per query.
    """
    text = (
        f"{service.get('name', '')} {service.get('description', '')} "
        f"{' '.join(service.get('tags', []))}"
    ).lower()

    categories = []
    for category, keywords in CAPABILITY_TAXONOMY.items():
        for kw in keywords:
            if kw in text:
                categories.append(f"{category}/{kw}")
                break
    return categories if categories else ["uncategorized"]


def normalize_service(raw: dict) -> dict:
    """Normalize a Bazaar service response to a standard shape."""
    return {
        "id": raw.get("id") or raw.get("service_id") or raw.get("agent_id", ""),
        "name": raw.get("name") or raw.get("title", "Unknown"),
        "description": raw.get("description", ""),
        "provider": raw.get("provider") or raw.get("publisher", "unknown"),
        "endpoint": raw.get("endpoint") or raw.get("mcp_endpoint", ""),
        "pricing": raw.get("pricing") or raw.get("price", {}),
        "tags": raw.get("tags", []),
        "rating": raw.get("rating", 0),
        "capabilities": [],
    }


# ─── Discover ──────────────────────────────────────────


def x402_discover(
    query: Optional[str] = None,
    category: Optional[str] = None,
    max_results: int = 20,
) -> list[dict]:
    """Discover agents/services via x402 Bazaar with taxonomy layer.

    Args:
        query: Optional text search query
        category: Optional Track C category filter (e.g. "ai/llm")
        max_results: Max results to return

    Returns:
        List of classified agent services.
    """
    client = X402Client()

    try:
        raw_services = client.search(query) if query else client.discover_mcp()
        normalized = [normalize_service(s) for s in raw_services]

        # Layer taxonomy
        for svc in normalized:
            svc["capabilities"] = classify_service(svc)

        # Filter by category if specified
        if category:
            normalized = [
                s for s in normalized
                if any(c.startswith(category) for c in s["capabilities"])
            ]

        # Sort by rating, limit
        normalized.sort(key=lambda s: s.get("rating", 0), reverse=True)
        return normalized[:max_results]

    except X402Error as e:
        logger.error(f"x402 discover failed: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error in x402 discover: {e}")
        return []


# ─── Payment ────────────────────────────────────────────


def x402_pay(
    service_id: str,
    amount: str,
    currency: str = "USDC",
    auto_settle: bool = True,
) -> dict:
    """Pay for an agent service via x402 protocol.

    Flow: request charge → wait for confirmation → optionally settle on-chain.

    Args:
        service_id: Service/agent to pay
        amount: Payment amount (e.g. "10.00")
        currency: Currency code (default "USDC")
        auto_settle: Call initiateFromX402 on-chain after payment

    Returns:
        Payment receipt dict.
    """
    client = X402Client()

    try:
        # Step 1: Request charge
        charge = client.request_charge(service_id, amount)
        charge_id = charge.get("charge_id", "")
        if not charge_id:
            return {"error": "No charge_id returned from Bazaar"}

        # Step 2: Wait for confirmation
        confirmation = client.wait_for_payment(charge_id)
        receipt_url = confirmation.get("receipt_url")

        # Step 3: On-chain settlement
        tx_hash = None
        status = "confirmed"
        if auto_settle:
            try:
                tx_hash = _settle_on_chain(charge_id, service_id, amount)
                status = "on_chain"
            except Exception as e:
                logger.warning(f"Settlement failed (non-fatal): {e}")
                status = "confirmed_pending_settlement"

        return {
            "success": True,
            "charge_id": charge_id,
            "service_id": service_id,
            "amount": amount,
            "currency": currency,
            "status": status,
            "transaction_hash": tx_hash,
            "receipt_url": receipt_url,
        }

    except X402Error as e:
        logger.error(f"x402 pay failed: {e}")
        return {"error": f"Payment failed: {e}"}
    except Exception as e:
        logger.exception(f"Unexpected error in x402 pay: {e}")
        return {"error": f"Unexpected error: {e}"}


def _settle_on_chain(charge_id: str, service_id: str, amount: str) -> str:
    """Call initiateFromX402 on the PaymentEscrow contract.

    In production this uses web3.py. For MVP, logs and returns a placeholder hash.
    """
    settings = get_x402_settings()

    if not settings.escrow_contract or not settings.payment_wallet_key:
        raise RuntimeError(
            "On-chain settlement requires ESCROW_CONTRACT_ADDRESS "
            "and PAYMENT_WALLET_PRIVATE_KEY environment variables"
        )

    logger.info(
        f"On-chain settlement: charge_id={charge_id}, "
        f"service_id={service_id}, amount={amount}, "
        f"contract={settings.escrow_contract}"
    )

    # Placeholder — web3.py integration comes in V1.5
    return f"0x{'x402' + charge_id.replace('-', '')[:62].lower()}"