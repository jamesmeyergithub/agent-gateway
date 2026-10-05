"""Unit and regression tests for Agent Gateway MCP tools and Agent configuration."""

import os
import unittest
from unittest.mock import patch, MagicMock

from app.mcp_server.tools import (
    lookup_order,
    view_customer_profile,
    issue_refund,
    delete_account,
    ORDER_DB,
    CUSTOMER_DB,
)


class TestAgentGatewayTools(unittest.TestCase):

    @patch("httpx.post")
    def test_lookup_order_allowed_via_gateway(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "order": {"order_id": "ORD-9001", "status": "Delivered", "item": "Cloud Workstation 32GB"},
        }
        mock_post.return_value = mock_resp

        result = lookup_order("ORD-9001")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["order"]["status"], "Delivered")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertTrue(call_args[0][0].endswith("/mcp"))
        self.assertEqual(call_args[1]["json"]["params"]["name"], "lookup_order")

    @patch("httpx.post")
    def test_lookup_order_blocked_by_gateway(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        result = lookup_order("ORD-9001")
        self.assertEqual(result["status"], "BLOCKED_BY_AGENT_GATEWAY")
        self.assertIn("403 Forbidden", result["error"])

    @patch("httpx.post", side_effect=Exception("Connection refused"))
    def test_lookup_order_fallback_offline(self, mock_post):
        result = lookup_order("ORD-9001")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["order"]["order_id"], "ORD-9001")
        self.assertEqual(result["order"]["item"], "Cloud Workstation 32GB")

    @patch("httpx.post")
    def test_issue_refund_blocked_by_gateway(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        result = issue_refund(order_id="ORD-9001", amount=50.0)
        self.assertEqual(result["status"], "BLOCKED_BY_AGENT_GATEWAY")
        self.assertIn("403 Forbidden", result["error"])
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[1]["json"]["params"]["name"], "issue_refund")

    @patch("httpx.post")
    def test_delete_account_blocked_by_gateway(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_post.return_value = mock_resp

        result = delete_account(customer_id="CUST-101")
        self.assertEqual(result["status"], "BLOCKED_BY_AGENT_GATEWAY")
        self.assertIn("403 Forbidden", result["error"])
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[1]["json"]["params"]["name"], "delete_account")

    def test_view_customer_profile(self):
        result = view_customer_profile("CUST-101")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["customer"]["name"], "Alice Montgomery")


if __name__ == "__main__":
    unittest.main()
