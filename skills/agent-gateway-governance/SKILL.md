---
name: agent-gateway-governance
description: Enforce Google Cloud IAM policies and Agent Gateway boundaries to restrict AI agents to assigned roles and prevent unauthorized tool executions.
---

# Agent Gateway Governance Skill

This skill guides the design, configuration, and enforcement of least-privilege boundary policies for autonomous agents using **Google Cloud Agent Platform**, **Agent Gateway**, and **Agent Identity (SPIFFE)**.

## Core Governance Concepts

1. **Managed Agent Gateway**: In Google Cloud Agent Platform, Agent Gateway is a managed networking and runtime security product that intercepts all traffic to and from agents (tool calls, MCP servers, external APIs, and Agent-to-Agent communication).
2. **First-Class Agent Identity**: Rather than using shared or long-lived service account keys, agents are provisioned cryptographic **Agent Identities** based on the CNCF **SPIFFE** standard:
   `spiffe://<project-id>.agentplatform.id.goog/agent/<agent-id>`
   or Google IAM Principal URI:
   `principal://agentidentity.googleapis.com/projects/<project-id>/locations/global/agentIdentities/<agent-id>`
3. **Agent-to-Tool & Agent-to-Service Binding**: The Agent Gateway validates tool calls against fine-grained IAM policies before any request reaches the backend service.
4. **Default-Deny Boundary**: Any tool or service not explicitly authorized for the caller's Agent Identity is rejected with `403 PermissionDenied`.
5. **Adversarial Resilience**: Prompt injection attacks or hallucinations attempting to call restricted tools (e.g., refunds, data deletion) are halted at the Gateway before executing backend code.

## IAM Binding Pattern

Map Agent Identities to specific custom IAM roles:
```json
{
  "role": "roles/agentgateway.supportViewer",
  "members": [
    "spiffe://${PROJECT_ID}.agentplatform.id.goog/agent/tier1-support-agent",
    "principal://agentidentity.googleapis.com/projects/${PROJECT_ID}/locations/global/agentIdentities/tier1-support-agent"
  ],
  "permissions": [
    "tools.customers.get",
    "tools.orders.get",
    "services.customerData.read"
  ]
}
```

## Running the Demo

To test the governance mechanisms locally:
```bash
uv run python demo.py
```
