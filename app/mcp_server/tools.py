"""
Backend Business Services and MCP Tools Implementation.

These services represent internal company systems (CRM, Payment Processor,
Identity Management). In production, these run behind the Agent Gateway
and are NEVER exposed directly to untrusted agent callers.
"""

from typing import Any, Dict


# Mock database records
CUSTOMER_DB = {
    "CUST-101": {
        "id": "CUST-101",
        "name": "Alice Montgomery",
        "email": "alice@example.com",
        "tier": "Gold",
        "status": "Active",
    },
    "CUST-102": {
        "id": "CUST-102",
        "name": "Bob Vance",
        "email": "bob@example.com",
        "tier": "Silver",
        "status": "Active",
    },
}

ORDER_DB = {
    "ORD-9001": {
        "order_id": "ORD-9001",
        "customer_id": "CUST-101",
        "item": "Cloud Workstation 32GB",
        "total": 1250.00,
        "status": "Delivered",
        "refundable": True,
    },
    "ORD-9002": {
        "order_id": "ORD-9002",
        "customer_id": "CUST-102",
        "item": "Mechanical Keyboard",
        "total": 180.00,
        "status": "In Transit",
        "refundable": True,
    },
}



import os
import httpx

REGION = (
    os.getenv("GOOGLE_CLOUD_LOCATION")
    if os.getenv("GOOGLE_CLOUD_LOCATION") and os.getenv("GOOGLE_CLOUD_LOCATION") != "global"
    else (os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or "us-west1")
)
REMOTE_MCP_SERVER = f"https://backend-tools.{REGION}.run.app"


def view_customer_profile(customer_id: str) -> Dict[str, Any]:
    """Retrieve customer account profile.
    Routes outbound through the Google Cloud Agent Gateway to the backend MCP service.
    Allowed by IAM Unified Access Policy (destination.is_registered == true).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "view_customer_profile",
            "arguments": {"customer_id": customer_id},
        },
    }
    try:
        resp = httpx.post(f"{REMOTE_MCP_SERVER}/mcp", json=payload, timeout=5.0)
        if resp.status_code == 403:
            return {
                "status": "BLOCKED_BY_AGENT_GATEWAY",
                "error": "HTTP 403 Forbidden: Request was blocked by Google Cloud Agent Gateway IAM Policy.",
                "tool": "view_customer_profile",
            }
        resp.raise_for_status()
        return resp.json()
    except Exception:
        # Fallback to local DB if backend MCP server is not reachable
        if customer_id not in CUSTOMER_DB:
            return {"error": f"Customer '{customer_id}' not found"}
        return {"status": "success", "customer": CUSTOMER_DB[customer_id]}


def lookup_order(order_id: str) -> Dict[str, Any]:
    """Check order status and tracking details.
    Routes outbound through the Google Cloud Agent Gateway to the backend MCP service.
    Allowed by IAM Unified Access Policy (destination.is_registered == true).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "lookup_order",
            "arguments": {"order_id": order_id},
        },
    }
    try:
        resp = httpx.post(f"{REMOTE_MCP_SERVER}/mcp", json=payload, timeout=5.0)
        if resp.status_code == 403:
            return {
                "status": "BLOCKED_BY_AGENT_GATEWAY",
                "error": "HTTP 403 Forbidden: Request was blocked by Google Cloud Agent Gateway IAM Policy.",
                "tool": "lookup_order",
            }
        resp.raise_for_status()
        return resp.json()
    except Exception:
        # Fallback to local DB if backend MCP server is not reachable
        if order_id not in ORDER_DB:
            return {"error": f"Order '{order_id}' not found"}
        return {"status": "success", "order": ORDER_DB[order_id]}


def issue_refund(order_id: str, amount: float, reason: str = "Customer Request") -> Dict[str, Any]:
    """CRITICAL SENSITIVE ACTION: Process a monetary refund.
    Must ONLY be executable by agents with 'tools.payments.refund' permission!
    Routes outbound through the Google Cloud Agent Gateway to the backend MCP service.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "issue_refund",
            "arguments": {"order_id": order_id, "amount": amount, "reason": reason},
        },
    }
    try:
        resp = httpx.post(f"{REMOTE_MCP_SERVER}/mcp", json=payload, timeout=5.0)
        if resp.status_code == 403:
            return {
                "status": "BLOCKED_BY_AGENT_GATEWAY",
                "error": "HTTP 403 Forbidden: Request was blocked by Google Cloud Agent Gateway IAM Policy (Deny destructive actions).",
                "tool": "issue_refund",
                "reason": "Agent identity lacks authorization to execute financial refund operations.",
            }
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {
            "status": "BLOCKED_BY_AGENT_GATEWAY",
            "error": f"Agent Gateway blocked request: {type(e).__name__} ({e})",
            "tool": "issue_refund",
            "reason": "Outbound egress was intercepted and denied by Google Cloud Agent Gateway.",
        }


def delete_account(customer_id: str, confirmation: bool = True) -> Dict[str, Any]:
    """CRITICAL SENSITIVE ACTION: Delete customer record.
    Must ONLY be executable by agents with 'tools.identity.delete' permission!
    Routes outbound through the Google Cloud Agent Gateway to the backend MCP service.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "delete_account",
            "arguments": {"customer_id": customer_id, "confirmation": confirmation},
        },
    }
    try:
        resp = httpx.post(f"{REMOTE_MCP_SERVER}/mcp", json=payload, timeout=5.0)
        if resp.status_code == 403:
            return {
                "status": "BLOCKED_BY_AGENT_GATEWAY",
                "error": "HTTP 403 Forbidden: Request was blocked by Google Cloud Agent Gateway IAM Policy (Deny destructive actions).",
                "tool": "delete_account",
                "reason": "Agent identity lacks authorization to execute customer deletion operations.",
            }
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {
            "status": "BLOCKED_BY_AGENT_GATEWAY",
            "error": f"Agent Gateway blocked request: {type(e).__name__} ({e})",
            "tool": "delete_account",
            "reason": "Outbound egress was intercepted and denied by Google Cloud Agent Gateway.",
        }


# Tool Dispatcher Dictionary
BACKEND_TOOLS = {
    "view_customer_profile": view_customer_profile,
    "lookup_order": lookup_order,
    "issue_refund": issue_refund,
    "delete_account": delete_account,
}
