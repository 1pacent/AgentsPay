"""Tests for x402 discover handler and core x402 module."""

import json
import unittest
from unittest.mock import patch, MagicMock

from app.handlers.x402_discover import handle_x402_discover
from app.x402 import classify_service, normalize_service, x402_discover, X402Error
from app.mcp_router import MCPError


class TestClassifyService(unittest.TestCase):
    """Test the Track C taxonomy layering logic."""

    def test_classify_by_description(self):
        svc = {"name": "GPT Text Gen", "description": "Generate text with LLM for summarization", "tags": ["nlp", "writing"]}
        cats = classify_service(svc)
        self.assertIn("ai/llm", cats)
        self.assertIn("ai/summarization", cats)
        self.assertIn("ai/generation", cats)

    def test_classify_by_tags(self):
        svc = {"name": "Payment Processor", "description": "", "tags": ["payment", "invoice"]}
        cats = classify_service(svc)
        self.assertIn("finance/payment", cats)

    def test_uncategorized_fallback(self):
        svc = {"name": "Zyx 9000", "description": "A novel service", "tags": ["unique"]}
        cats = classify_service(svc)
        self.assertEqual(cats, ["uncategorized"])

    def test_multiple_categories(self):
        svc = {"name": "Data Analyzer AI", "description": "Analytics with LLM query generation", "tags": ["analytics", "ai"]}
        cats = classify_service(svc)
        self.assertIn("data/analytics", cats)
        self.assertIn("ai/llm", cats)


class TestNormalizeService(unittest.TestCase):
    """Test service normalization from Bazaar shapes."""

    def test_standard_shape(self):
        raw = {"id": "svc_1", "name": "LLM Gen", "description": "Text generation", "provider": "openai", "tags": ["llm"]}
        n = normalize_service(raw)
        self.assertEqual(n["id"], "svc_1")
        self.assertEqual(n["name"], "LLM Gen")
        self.assertEqual(n["provider"], "openai")

    def test_alternate_keys(self):
        raw = {"service_id": "alt_1", "title": "Alt Service", "publisher": "altcorp"}
        n = normalize_service(raw)
        self.assertEqual(n["id"], "alt_1")
        self.assertEqual(n["name"], "Alt Service")
        self.assertEqual(n["provider"], "altcorp")

    def test_empty_fallback(self):
        raw = {}
        n = normalize_service(raw)
        self.assertEqual(n["name"], "Unknown")
        self.assertEqual(n["provider"], "unknown")


class TestX402Discover(unittest.TestCase):
    """Test the x402 discover flow."""

    @patch("app.x402.X402Client")
    def test_discover_all(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.discover_mcp.return_value = [
            {"id": "svc_1", "name": "LLM Gen", "description": "LLM text generation", "provider": "openai", "tags": ["llm"], "rating": 4.5},
            {"id": "svc_2", "name": "Payment API", "description": "Process USDC payments", "provider": "circle", "tags": ["payment"], "rating": 4.0},
        ]
        mock_client_cls.return_value = mock_client

        results = x402_discover()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "LLM Gen")
        self.assertIn("ai/llm", results[0]["capabilities"])
        self.assertIn("finance/payment", results[1]["capabilities"])

    @patch("app.x402.X402Client")
    def test_discover_with_query(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.search.return_value = [{"id": "svc_3", "name": "Auditor", "description": "Smart contract audit", "provider": "certik", "tags": ["solidity"]}]
        mock_client_cls.return_value = mock_client

        results = x402_discover(query="smart contract audit")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Auditor")
        mock_client.search.assert_called_once_with("smart contract audit")
        mock_client.discover_mcp.assert_not_called()

    @patch("app.x402.X402Client")
    def test_discover_with_category_filter(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.discover_mcp.return_value = [
            {"id": "svc_1", "name": "LLM Chat", "description": "Chat using LLM", "tags": ["llm"]},
            {"id": "svc_2", "name": "Data Warehouse", "description": "Store and query data", "tags": ["storage"]},
        ]
        mock_client_cls.return_value = mock_client

        results = x402_discover(category="ai")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "LLM Chat")

    @patch("app.x402.X402Client")
    def test_discover_api_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.discover_mcp.side_effect = X402Error("API down")
        mock_client_cls.return_value = mock_client

        results = x402_discover()
        self.assertEqual(results, [])

    @patch("app.x402.X402Client")
    def test_max_results_limit(self, mock_client_cls):
        mock_client = MagicMock()
        services = [{"id": f"svc_{i}", "name": f"Service {i}", "description": f"LLM service {i}", "tags": ["llm"]} for i in range(50)]
        mock_client.discover_mcp.return_value = services
        mock_client_cls.return_value = mock_client

        results = x402_discover(max_results=5)
        self.assertEqual(len(results), 5)


class TestHandleX402Discover(unittest.TestCase):
    """Test the MCP handler wrapper."""

    def test_invalid_query_type(self):
        with self.assertRaises(MCPError):
            handle_x402_discover({"query": 123})

    def test_invalid_category_type(self):
        with self.assertRaises(MCPError):
            handle_x402_discover({"category": 456})

    def test_valid_discover(self):
        with patch("app.handlers.x402_discover._x402_discover", return_value=[{"id": "svc_1", "name": "Test"}]):
            result = handle_x402_discover({"query": "test", "max_results": 10})
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["source"], "x402_bazaar")


if __name__ == "__main__":
    unittest.main()