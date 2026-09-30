"""
Agent Gateway IAM Policy Engine.

Enforces Google Cloud IAM-style Least-Privilege access control on:
1. Agent-to-Tool communications (Fine-grained tool permissions)
2. Agent-to-Service communications (Coarse-grained service permissions)

Evaluates permissions directly against first-class SPIFFE Agent Identities.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from app.gateway.auth import AgentIdentity
except ImportError:
    from gateway.auth import AgentIdentity


@dataclass
class PolicyEvaluationResult:
    allowed: bool
    agent_identity: str
    spiffe_id: str
    tool_name: str
    target_service: str
    required_permission: str
    matched_role: Optional[str]
    reason: str
    timestamp: float


class AgentGatewayPolicyEngine:
    """Evaluates IAM policies and acts as the Policy Enforcement Point (PEP)."""

    def __init__(self, policy_file_path: Optional[str] = None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "demo-cloud-project")
        if policy_file_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            policy_file_path = str(base_dir / "config" / "iam_policy.json")

        self.policy_file_path = policy_file_path
        self.audit_log: List[Dict[str, Any]] = []
        self._load_policy()

    def _load_policy(self) -> None:
        """Loads and resolves variables in the IAM policy file."""
        with open(self.policy_file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        # Interpolate ${PROJECT_ID}
        interpolated = raw_content.replace("${PROJECT_ID}", self.project_id)
        self.policy_data = json.loads(interpolated)
        self.bindings = self.policy_data.get("bindings", [])
        self.tool_registry = self.policy_data.get("tool_registry", {})

    def evaluate_tool_access(
        self, identity: AgentIdentity, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> PolicyEvaluationResult:
        """
        Evaluate if the Agent Identity is authorized to invoke tool_name.
        Default-Deny model: If no IAM binding grants permission, access is DENIED.
        """
        now = time.time()

        # 1. Check if tool is known in the registry
        if tool_name not in self.tool_registry:
            result = PolicyEvaluationResult(
                allowed=False,
                agent_identity=identity.agent_id,
                spiffe_id=identity.spiffe_id,
                tool_name=tool_name,
                target_service="unknown",
                required_permission="tools.unknown.execute",
                matched_role=None,
                reason=f"Tool '{tool_name}' is not registered with Agent Gateway.",
                timestamp=now,
            )
            self._record_audit(result, arguments)
            return result

        tool_meta = self.tool_registry[tool_name]
        required_perm = tool_meta["required_permission"]
        target_service = tool_meta["target_service"]

        # 2. Match bindings for Agent Identity
        matched_roles = []
        for binding in self.bindings:
            members = binding.get("members", [])
            permissions = binding.get("permissions", [])

            # Check if this Agent Identity matches any member pattern
            is_member = any(identity.matches(member) for member in members)
            if is_member and required_perm in permissions:
                matched_roles.append(binding.get("role"))

        # 3. Decision
        if matched_roles:
            result = PolicyEvaluationResult(
                allowed=True,
                agent_identity=identity.agent_id,
                spiffe_id=identity.spiffe_id,
                tool_name=tool_name,
                target_service=target_service,
                required_permission=required_perm,
                matched_role=matched_roles[0],
                reason=f"Granted by IAM role '{matched_roles[0]}' containing permission '{required_perm}'.",
                timestamp=now,
            )
        else:
            result = PolicyEvaluationResult(
                allowed=False,
                agent_identity=identity.agent_id,
                spiffe_id=identity.spiffe_id,
                tool_name=tool_name,
                target_service=target_service,
                required_permission=required_perm,
                matched_role=None,
                reason=(
                    f"Agent Identity '{identity.spiffe_id}' lacks required IAM permission "
                    f"'{required_perm}' for tool '{tool_name}' on service '{target_service}'."
                ),
                timestamp=now,
            )

        self._record_audit(result, arguments)
        return result

    def get_authorized_tools(self, identity: AgentIdentity) -> Dict[str, Dict[str, Any]]:
        """Return subset of tools that the Agent Identity is authorized to execute."""
        authorized = {}
        for tool_name, tool_meta in self.tool_registry.items():
            required_perm = tool_meta["required_permission"]
            for binding in self.bindings:
                members = binding.get("members", [])
                if any(identity.matches(member) for member in members):
                    if required_perm in binding.get("permissions", []):
                        authorized[tool_name] = tool_meta
                        break
        return authorized

    def _record_audit(self, result: PolicyEvaluationResult, arguments: Optional[Dict[str, Any]]) -> None:
        """Record entry to Gateway Audit Log."""
        entry = {
            "timestamp": result.timestamp,
            "verdict": "ALLOW" if result.allowed else "DENY",
            "agent_identity": result.agent_identity,
            "spiffe_id": result.spiffe_id,
            "tool_name": result.tool_name,
            "target_service": result.target_service,
            "required_permission": result.required_permission,
            "matched_role": result.matched_role,
            "reason": result.reason,
            "arguments": arguments or {},
        }
        self.audit_log.append(entry)


# Singleton engine instance
policy_engine = AgentGatewayPolicyEngine()
