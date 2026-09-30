"""
Gemini / Vertex AI Agent Integration with Agent Gateway.

Uses Google Cloud Application Default Credentials (ADC) to interact with
Gemini on Vertex AI (NO API keys needed!).

The agent is provided tool definitions pointing to the Agent Gateway.
When the agent generates tool calls, they are routed through the Gateway,
where IAM policies prevent the agent from performing actions outside its role.
"""

import os
from typing import Any, Dict, List, Optional
from agent.client import AgentGatewayClient


class Tier1SupportAgent:
    """
    Tier 1 Customer Support Agent.
    Assigned Role: Answer customer inquiries, look up order statuses.
    Forbidden Actions: Modifying accounts, issuing financial refunds, deleting data.
    """

    def __init__(
        self,
        gateway_client: AgentGatewayClient,
        project_id: Optional[str] = None,
        location: str = "us-central1",
    ):
        self.gateway = gateway_client
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "demo-cloud-project")
        self.location = location
        self._init_vertex_ai()

    def _init_vertex_ai(self):
        """Initializes Google GenAI Client with Vertex AI and Application Default Credentials."""
        self.gemini_client = None
        try:
            from google import genai
            # Pure Google Cloud ADC - No third party API keys
            self.gemini_client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
        except Exception:
            # If ADC/Vertex is not configured locally, fallback to simulator mode
            self.gemini_client = None

    def execute_user_request(self, user_prompt: str) -> Dict[str, Any]:
        """
        Process a user prompt. If the user prompt requests an action,
        decide which tool to invoke and pass it to the Agent Gateway.
        """
        # Determine intent: In production, Gemini determines function calls.
        # Here we parse or mock the LLM function call to demonstrate
        # what happens when the LLM is tricked into calling an unauthorized tool.
        tool_call_to_make = self._plan_tool_call(user_prompt)

        if not tool_call_to_make:
            return {
                "agent_response": "I can only help with order inquiries and account questions.",
                "tool_called": None,
                "status": "NO_TOOL_INVOKED",
            }

        tool_name = tool_call_to_make["name"]
        tool_args = tool_call_to_make["arguments"]

        # Call the tool through the Agent Gateway
        gateway_response = self.gateway.invoke_tool(tool_name, tool_args)

        if gateway_response.get("status") == "BLOCKED_BY_GATEWAY":
            # Agent catches IAM policy denial from Gateway
            policy_err = gateway_response["error"]
            return {
                "agent_response": (
                    f"⚠️ ACTION BLOCKED: I attempted to execute '{tool_name}', but the "
                    f"Agent Gateway denied access. Reason: {policy_err.get('message')}"
                ),
                "gateway_verdict": "DENY",
                "tool_called": tool_name,
                "details": gateway_response,
            }

        elif gateway_response.get("status") == "SUCCESS":
            return {
                "agent_response": (
                    f"✅ SUCCESS: Executed '{tool_name}' through Agent Gateway. "
                    f"Result: {gateway_response.get('result')}"
                ),
                "gateway_verdict": "ALLOW",
                "tool_called": tool_name,
                "details": gateway_response,
            }

        return {
            "agent_response": f"Unexpected error: {gateway_response}",
            "gateway_verdict": "ERROR",
            "details": gateway_response,
        }

    def _plan_tool_call(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Simulates or extracts the LLM function call based on prompt intent."""
        lower = prompt.lower()

        # Prompt Injection / Privilege Escalation test cases
        if "refund" in lower or "money" in lower or "override" in lower:
            # Malicious prompt tricked the agent into calling sensitive refund tool!
            return {
                "name": "issue_refund",
                "arguments": {
                    "order_id": "ORD-9001",
                    "amount": 500.0,
                    "reason": "Customer escalated threat",
                },
            }
        elif "delete" in lower or "erase" in lower:
            return {
                "name": "delete_account",
                "arguments": {"customer_id": "CUST-101", "confirmation": True},
            }
        elif "order" in lower:
            return {
                "name": "lookup_order",
                "arguments": {"order_id": "ORD-9001"},
            }
        elif "profile" in lower or "customer" in lower:
            return {
                "name": "view_customer_profile",
                "arguments": {"customer_id": "CUST-101"},
            }

        return None
