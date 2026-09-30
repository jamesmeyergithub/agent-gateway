"""
Agent Gateway Client for AI Agents.

Agents use this client to interact with tools and services strictly via
the Agent Gateway, passing their authenticated Agent Identity.
"""

from typing import Any, Dict, List, Optional
import httpx


class AgentGatewayClient:
    """Client for routing agent tool calls through Google Cloud Agent Gateway."""

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:8000",
        agent_identity: str = "tier1-support-agent",
        auth_token: Optional[str] = None,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.agent_identity = agent_identity
        self.auth_token = auth_token

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Identity": self.agent_identity,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def list_available_tools(self) -> List[Dict[str, Any]]:
        """Fetch list of tools registered on Agent Gateway."""
        url = f"{self.gateway_url}/gateway/v1/tools"
        with httpx.Client() as client:
            resp = client.get(url, headers=self._get_headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("tools", [])

    def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tool call via Agent Gateway.
        Returns execution result if allowed, or error details if blocked by IAM.
        """
        url = f"{self.gateway_url}/gateway/v1/tools/call"
        payload = {"name": tool_name, "arguments": arguments}

        with httpx.Client() as client:
            resp = client.post(url, json=payload, headers=self._get_headers())

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 403:
                # Gateway Blocked the Agent!
                error_body = resp.json().get("detail", {})
                return {
                    "status": "BLOCKED_BY_GATEWAY",
                    "policy_verdict": "DENY",
                    "tool_name": tool_name,
                    "error": error_body,
                }
            else:
                return {
                    "status": "HTTP_ERROR",
                    "status_code": resp.status_code,
                    "text": resp.text,
                }

    def invoke_mcp_rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invoke using standard Model Context Protocol (MCP) JSON-RPC 2.0 format."""
        url = f"{self.gateway_url}/gateway/mcp/v1"
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

        with httpx.Client() as client:
            resp = client.post(url, json=payload, headers=self._get_headers())
            return resp.json()
