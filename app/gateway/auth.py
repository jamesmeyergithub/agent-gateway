"""
Google Cloud Agent Platform: Agent Identity Authentication & Verification.

In Google Cloud Agent Platform (and Gemini Enterprise):
- AI Agents are first-class principals identified by **Agent Identities** rather than
  generic shared service accounts.
- Agent Identities are formatted using the open-source **SPIFFE** standard:
  `spiffe://<project-id>.agentplatform.id.goog/agent/<agent-id>`
  or Google Cloud Principal URI:
  `principal://agentidentity.googleapis.com/projects/<project-id>/locations/global/agentIdentities/<agent-id>`
- The Agent Platform Runtime manages short-lived cryptographic X.509 certificates
  and bound DPoP (Demonstrating Proof-of-Possession) tokens.
- The managed **Agent Gateway** intercepts egress and inspects the Agent Identity
  before validating IAM policies.
"""

import os
from typing import Optional
from fastapi import Header, HTTPException, status


class AgentIdentity:
    """Represents a first-class Agent Identity in Google Cloud Agent Platform."""

    def __init__(
        self,
        agent_id: str,
        project_id: Optional[str] = None,
        spiffe_id: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "demo-cloud-project")
        
        # SPIFFE ID standard format:
        # spiffe://<project-id>.agentplatform.id.goog/agent/<agent-id>
        self.spiffe_id = spiffe_id or f"spiffe://{self.project_id}.agentplatform.id.goog/agent/{self.agent_id}"

        # Google Cloud IAM Principal URI:
        self.principal_uri = (
            f"principal://agentidentity.googleapis.com/projects/{self.project_id}/"
            f"locations/global/agentIdentities/{self.agent_id}"
        )

    def matches(self, member_pattern: str) -> bool:
        """Checks if this Agent Identity satisfies an IAM binding member string."""
        return (
            member_pattern == self.spiffe_id
            or member_pattern == self.principal_uri
            or member_pattern.endswith(f"/agent/{self.agent_id}")
            or member_pattern.endswith(f"/agentIdentities/{self.agent_id}")
            or member_pattern == "allAuthenticatedAgents"
        )

    def __repr__(self) -> str:
        return f"<AgentIdentity id={self.agent_id} spiffe={self.spiffe_id}>"


def resolve_agent_identity(
    authorization: Optional[str] = Header(None),
    x_agent_identity: Optional[str] = Header(None),
    x_spiffe_id: Optional[str] = Header(None),
) -> AgentIdentity:
    """
    Resolves the incoming Agent Identity.
    
    In production Agent Platform:
    - Injected automatically via Agent Platform Runtime and verified via mTLS / SPIFFE.
    - Or extracted from short-lived DPoP-bound tokens.
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "demo-cloud-project")

    # 1. Direct SPIFFE ID header (passed via mTLS SAN or Gateway header)
    if x_spiffe_id:
        agent_name = x_spiffe_id.split("/")[-1]
        return AgentIdentity(agent_id=agent_name, project_id=project_id, spiffe_id=x_spiffe_id)

    # 2. Agent Identity Name
    if x_agent_identity:
        agent_name = x_agent_identity.replace("agent-", "").strip()
        # Clean agent identifier
        if "tier1" in x_agent_identity:
            agent_name = "tier1-support-agent"
        elif "billing" in x_agent_identity:
            agent_name = "billing-specialist"
        elif "secops" in x_agent_identity:
            agent_name = "secops-admin"
        else:
            agent_name = x_agent_identity
        return AgentIdentity(agent_id=agent_name, project_id=project_id)

    # 3. Authorization Bearer Token (Agent Platform Runtime Token)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
        if token.startswith("agent-id:"):
            agent_name = token.replace("agent-id:", "")
            return AgentIdentity(agent_id=agent_name, project_id=project_id)

    # Default fallback: Tier 1 Support Agent (Least privileged identity)
    return AgentIdentity(agent_id="tier1-support-agent", project_id=project_id)
