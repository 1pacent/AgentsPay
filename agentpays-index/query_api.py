"""CLI + HTTP API server for Capability Index.

Stdlib-only HTTP server — zero extra dependencies.
Supports:
  GET  /query/category?category=data_extraction&max_price=0.005&min_trust=0.8
  GET  /health
  POST /agent/register
"""

import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any

from capability_index import (
    init_db,
    cached_query,
    register_agent,
    query_by_category,
    CAPABILITY_CATEGORIES,
    invalidate_cache,
)

logger = logging.getLogger("agentpays.api")


class CapabilityAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Capability Index API."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/health":
            self._json_response({"status": "ok", "categories": len(CAPABILITY_CATEGORIES)})

        elif path == "/query/category":
            self._handle_query(params)

        elif path == "/query/all":
            self._handle_all()

        elif path == "/cache/clear":
            invalidate_cache()
            self._json_response({"status": "ok", "cache": "cleared"})

        else:
            self._json_response({"error": "Not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json_response({"error": "Invalid JSON"}, status=400)
            return

        if path == "/agent/register":
            self._handle_register(data)
        else:
            self._json_response({"error": "Not found"}, status=404)

    def _handle_query(self, params: dict[str, list[str]]):
        category = params.get("category", [None])[0]
        if not category:
            self._json_response({"error": "category parameter is required"}, status=400)
            return

        max_price = params.get("max_price", [None])[0]
        min_trust = params.get("min_trust", [None])[0]
        limit = int(params.get("limit", ["20"])[0])

        results = cached_query(
            category=category,
            max_price=float(max_price) if max_price else None,
            min_trust=float(min_trust) if min_trust else None,
            limit=limit,
        )

        self._json_response({
            "category": category,
            "count": len(results),
            "agents": results,
        })

    def _handle_all(self):
        all_agents = []
        for cat in CAPABILITY_CATEGORIES:
            all_agents.extend(cached_query(category=cat))
        self._json_response({
            "count": len(all_agents),
            "agents": all_agents,
        })

    def _handle_register(self, data: dict[str, Any]):
        required = ["agent_id", "name", "capability_category", "endpoint_url"]
        missing = [f for f in required if f not in data]
        if missing:
            self._json_response({
                "error": f"Missing required fields: {', '.join(missing)}"
            }, status=400)
            return

        try:
            register_agent(
                agent_id=data["agent_id"],
                name=data["name"],
                description=data.get("description", ""),
                capability_category=data["capability_category"],
                endpoint_url=data["endpoint_url"],
                price_min=float(data.get("price_min", 0)),
                price_max=float(data["price_max"]) if data.get("price_max") else None,
                trust_score=float(data.get("trust_score", 0.5)),
                wallet_address=data.get("wallet_address"),
                agent_card_url=data.get("agent_card_url"),
                slow_path_eligible=bool(data.get("slow_path_eligible", False)),
            )
            invalidate_cache()
            self._json_response({"status": "ok", "agent_id": data["agent_id"]}, status=201)
        except ValueError as e:
            self._json_response({"error": str(e)}, status=400)

    def _json_response(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")


def serve(host: str = "0.0.0.0", port: int = 8080):
    """Start the HTTP API server."""
    init_db()
    server = HTTPServer((host, port), CapabilityAPIHandler)
    logger.info(f"Capability Index API server listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down")
        server.server_close()