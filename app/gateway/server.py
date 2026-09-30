"""
Google Cloud Agent Platform: Agent Gateway Service (Local Gateway Emulator).

Acts as the Policy Enforcement Point (PEP) between Agents and Tools/Services.
In production, Agent Gateway is a fully-managed Google Cloud Agent Platform service.
This server provides the local developer emulation of the Agent Gateway, enforcing
the exact same SPIFFE Agent Identity validation, IAM policy checks, and MCP mediation.
"""

from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from gateway.auth import AgentIdentity, resolve_agent_identity
from gateway.policy_engine import policy_engine
from mcp_server.tools import BACKEND_TOOLS

app = FastAPI(
    title="Google Cloud Agent Platform - Agent Gateway",
    description="Centralized Policy Enforcement Point for Agent Identity, Tools, and Services Governance",
    version="2.0.0",
)


# Request & Response Schemas
class ToolCallRequest(BaseModel):
    name: str = Field(..., description="Tool name to invoke")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for the tool")


class ToolCallResponse(BaseModel):
    status: str
    tool_name: str
    policy_verdict: str
    agent_identity: str
    spiffe_id: str
    result: Optional[Any] = None
    error: Optional[str] = None


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Optional[Dict[str, Any]] = None
    id: Optional[Any] = 1


@app.get("/health")
def health_check():
    return {
        "status": "HEALTHY",
        "service": "Google Cloud Agent Platform - Agent Gateway (Emulator)",
        "identity_standard": "SPIFFE / Google Cloud Agent Identity",
    }


@app.get("/gateway/v1/tools")
def list_tools(identity: AgentIdentity = Depends(resolve_agent_identity)):
    """
    List tools registered on the Agent Gateway (backed by Agent Registry).
    Filters tools based on the caller's Agent Identity.
    """
    authorized = policy_engine.get_authorized_tools(identity)
    all_tools = policy_engine.tool_registry

    response = []
    for tool_name, meta in all_tools.items():
        is_allowed = tool_name in authorized
        response.append({
            "name": tool_name,
            "description": meta["description"],
            "target_service": meta["target_service"],
            "required_permission": meta["required_permission"],
            "authorized_for_agent": is_allowed,
        })

    return {
        "agent_identity": identity.agent_id,
        "spiffe_id": identity.spiffe_id,
        "tools": response,
    }


@app.post("/gateway/v1/tools/call", response_model=ToolCallResponse)
def execute_tool_call(
    request: ToolCallRequest,
    identity: AgentIdentity = Depends(resolve_agent_identity),
):
    """
    Execute a tool call with Agent Gateway IAM policy enforcement.
    Blocks any agent trying to exceed its assigned role!
    """
    eval_result = policy_engine.evaluate_tool_access(
        identity=identity,
        tool_name=request.name,
        arguments=request.arguments,
    )

    if not eval_result.allowed:
        # Access is blocked at the Agent Gateway BEFORE reaching backend services!
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "PERMISSION_DENIED",
                "policy_verdict": "DENY",
                "agent_identity": identity.agent_id,
                "spiffe_id": identity.spiffe_id,
                "tool_name": request.name,
                "target_service": eval_result.target_service,
                "required_permission": eval_result.required_permission,
                "message": eval_result.reason,
            },
        )

    # Execution is authorized -> Delegate to backend service
    backend_fn = BACKEND_TOOLS.get(request.name)
    if not backend_fn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backend implementation for tool '{request.name}' not found.",
        )

    try:
        execution_result = backend_fn(**request.arguments)
        return ToolCallResponse(
            status="SUCCESS",
            tool_name=request.name,
            policy_verdict="ALLOW",
            agent_identity=identity.agent_id,
            spiffe_id=identity.spiffe_id,
            result=execution_result,
        )
    except Exception as e:
        return ToolCallResponse(
            status="ERROR",
            tool_name=request.name,
            policy_verdict="ALLOW",
            agent_identity=identity.agent_id,
            spiffe_id=identity.spiffe_id,
            error=str(e),
        )


@app.post("/gateway/mcp/v1")
def mcp_jsonrpc_endpoint(
    rpc_req: JsonRpcRequest,
    identity: AgentIdentity = Depends(resolve_agent_identity),
):
    """
    Model Context Protocol (MCP) JSON-RPC 2.0 Gateway Endpoint.
    Enforces IAM policies on standard MCP tools/call requests using Agent Identity.
    """
    if rpc_req.method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_req.id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "AgentPlatform-AgentGateway-MCP", "version": "2.0.0"},
            },
        }

    elif rpc_req.method == "tools/list":
        authorized = policy_engine.get_authorized_tools(identity)
        tools_list = []
        for name, meta in authorized.items():
            tools_list.append({
                "name": name,
                "description": meta["description"],
                "inputSchema": {"type": "object", "properties": {}},
            })
        return {
            "jsonrpc": "2.0",
            "id": rpc_req.id,
            "result": {"tools": tools_list},
        }

    elif rpc_req.method == "tools/call":
        params = rpc_req.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        eval_result = policy_engine.evaluate_tool_access(
            identity=identity,
            tool_name=tool_name,
            arguments=arguments,
        )

        if not eval_result.allowed:
            # Return JSON-RPC Error -32003 (Permission Denied)
            return {
                "jsonrpc": "2.0",
                "id": rpc_req.id,
                "error": {
                    "code": -32003,
                    "message": f"Agent Gateway IAM Policy Violation: {eval_result.reason}",
                    "data": {
                        "agent_identity": identity.agent_id,
                        "spiffe_id": identity.spiffe_id,
                        "required_permission": eval_result.required_permission,
                    },
                },
            }

        backend_fn = BACKEND_TOOLS.get(tool_name)
        if not backend_fn:
            return {
                "jsonrpc": "2.0",
                "id": rpc_req.id,
                "error": {"code": -32601, "message": f"Method {tool_name} not found"},
            }

        res = backend_fn(**arguments)
        return {
            "jsonrpc": "2.0",
            "id": rpc_req.id,
            "result": {"content": [{"type": "text", "text": str(res)}]},
        }

    return {
        "jsonrpc": "2.0",
        "id": rpc_req.id,
        "error": {"code": -32601, "message": f"Method {rpc_req.method} not supported"},
    }


@app.get("/gateway/v1/audit-logs")
def get_audit_logs():
    """Retrieve full audit history recorded by Agent Gateway."""
    return {"count": len(policy_engine.audit_log), "logs": policy_engine.audit_log}
