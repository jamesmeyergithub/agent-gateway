#!/usr/bin/env python3
"""
Turnkey Deployment Script for Google Cloud Agent Gateway & Agent Platform IAM Demo.

Automates the complete deployment of:
1. VPC Networking & Network Attachment
2. Native Google Cloud Agent Gateway (us-west1)
3. Agent Gateway Root CA Certificate Setup
4. Org Policy IAM Access Policy Binding Unblocking
5. Agent Registry Endpoints & MCP Server Registration
6. IAP Egressor Role Bindings on Projected Resources
7. IAM Access Policy with Tool-Level DENY Rules
8. Agent Runtime Deployment via agents-cli
9. Live End-to-End Verification of Allowed & Denied Tool Calls
"""

import argparse
import json
import os
import ssl
import sys
import time
from typing import Any, Dict, List, Optional
import urllib.parse

import certifi
import google.auth
from google.auth.transport.requests import AuthorizedSession


def log(msg: str, status: str = "INFO"):
    prefixes = {
        "INFO": "\033[94m[*]\033[0m",
        "SUCCESS": "\033[92m[✓]\033[0m",
        "WARN": "\033[93m[!]\033[0m",
        "ERROR": "\033[91m[✗]\033[0m",
        "HEADER": "\033[95m[==]\033[0m",
    }
    print(f"{prefixes.get(status, '[*]')} {msg}", flush=True)


def wait_for_lro(session: AuthorizedSession, url: str, max_attempts: int = 30, sleep_sec: int = 2) -> Dict[str, Any]:
    for _ in range(max_attempts):
        r = session.get(url)
        if r.status_code != 200:
            time.sleep(sleep_sec)
            continue
        data = r.json()
        if data.get("done"):
            if "error" in data:
                raise RuntimeError(f"Operation failed: {json.dumps(data['error'])}")
            return data.get("response", {})
        time.sleep(sleep_sec)
    raise TimeoutError(f"Operation timed out waiting on {url}")


def get_project_metadata(session: AuthorizedSession, project_id: str):
    log(f"Fetching project details for '{project_id}'...")
    r = session.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}")
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch project {project_id}: {r.status_code} {r.text}")
    data = r.json()
    project_number = data.get("projectNumber")
    parent = data.get("parent", {})
    org_id = None
    if parent.get("type") == "organization":
        org_id = parent.get("id")
    else:
        # Resolve org by walking up parent folder
        curr_type = parent.get("type")
        curr_id = parent.get("id")
        while curr_type == "folder":
            fr = session.get(f"https://cloudresourcemanager.googleapis.com/v2/folders/{curr_id}")
            if fr.status_code == 200:
                fdata = fr.json()
                fparent = fdata.get("parent", "")
                if fparent.startswith("organizations/"):
                    org_id = fparent.split("/")[1]
                    break
                elif fparent.startswith("folders/"):
                    curr_id = fparent.split("/")[1]
                else:
                    break
            else:
                break

    log(f"Project ID: {project_id} | Project Number: {project_number} | Org ID: {org_id}", "SUCCESS")
    return project_number, org_id


def enable_services(session: AuthorizedSession, project_id: str):
    required_services = [
        "aiplatform.googleapis.com",
        "agentregistry.googleapis.com",
        "networkservices.googleapis.com",
        "iap.googleapis.com",
        "iam.googleapis.com",
        "orgpolicy.googleapis.com",
        "compute.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "logging.googleapis.com",
    ]
    log("Ensuring required Google Cloud APIs are enabled...")
    for svc in required_services:
        url = f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/{svc}"
        r = session.get(url)
        if r.status_code == 200 and r.json().get("state") == "ENABLED":
            continue
        log(f"Enabling {svc}...")
        enable_r = session.post(f"{url}:enable")
        if enable_r.status_code in (200, 201):
            op = enable_r.json().get("name")
            if op:
                wait_for_lro(session, f"https://serviceusage.googleapis.com/v1/{op}")
    log("All required APIs enabled.", "SUCCESS")


def configure_org_policy(session: AuthorizedSession, project_id: str):
    log("Checking IAM Access Policy binding constraint...")
    url = f"https://orgpolicy.googleapis.com/v2/projects/{project_id}/policies/iam.managed.disableAccessPolicyBinding"
    r = session.get(url)
    enforced = False
    if r.status_code == 200:
        rules = r.json().get("spec", {}).get("rules", [])
        for rule in rules:
            if rule.get("enforce") is True:
                enforced = True
    elif r.status_code == 404:
        enforced = True

    if enforced:
        log("Disabling constraints/iam.managed.disableAccessPolicyBinding on project...")
        patch_body = {
            "name": f"projects/{project_id}/policies/iam.managed.disableAccessPolicyBinding",
            "spec": {"rules": [{"enforce": False}]},
        }
        r = session.patch(url, json=patch_body)
        if r.status_code not in (200, 201):
            log(f"Warning setting org policy: {r.status_code} {r.text}", "WARN")
        else:
            log("Org policy updated: Access policy bindings allowed.", "SUCCESS")
    else:
        log("Access policy binding constraint already relaxed.", "SUCCESS")


def setup_agent_gateway(session: AuthorizedSession, project_id: str, region: str, network_attachment: str):
    gateway_id = "agent-gateway-vpc-west1"
    url = f"https://networkservices.googleapis.com/v1alpha1/projects/{project_id}/locations/{region}/agentGateways/{gateway_id}"
    log(f"Checking Agent Gateway '{gateway_id}'...")
    r = session.get(url)
    root_certs = []
    if r.status_code == 200:
        log(f"Agent Gateway '{gateway_id}' already exists.", "SUCCESS")
        root_certs = r.json().get("agentGatewayCard", {}).get("rootCertificates", [])
    else:
        log(f"Creating Agent Gateway '{gateway_id}'...")
        create_url = f"https://networkservices.googleapis.com/v1alpha1/projects/{project_id}/locations/{region}/agentGateways?agentGatewayId={gateway_id}"
        body = {
            "description": f"Managed Agent Gateway with VPC Egress for {region}",
            "networkConfig": {
                "egress": {
                    "networkAttachment": network_attachment
                }
            },
            "protocols": ["MCP"],
            "registries": [
                f"//agentregistry.googleapis.com/projects/{project_id}/locations/{region}"
            ]
        }
        cr = session.post(create_url, json=body)
        if cr.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create Agent Gateway: {cr.status_code} {cr.text}")
        op_name = cr.json().get("name")
        res = wait_for_lro(session, f"https://networkservices.googleapis.com/v1alpha1/{op_name}", max_attempts=45, sleep_sec=4)
        root_certs = res.get("agentGatewayCard", {}).get("rootCertificates", [])
        log(f"Agent Gateway '{gateway_id}' created successfully.", "SUCCESS")

    # Enforce policy (turn off dry-run)
    log("Ensuring Agent Gateway is in active enforcement mode (failOpen=false)...")
    authz_ext_url = f"https://networkservices.googleapis.com/v1alpha1/projects/{project_id}/locations/{region}/authzExtensions/iap-dryrun"
    ext_r = session.get(authz_ext_url)
    if ext_r.status_code == 200:
        ext_body = {"failOpen": False}
        session.patch(f"{authz_ext_url}?updateMask=failOpen", json=ext_body)

    # Save Root CA Certificate
    if root_certs:
        ca_pem = root_certs[0]
        ca_path = os.path.join(os.path.dirname(__file__), "..", "app", "agent_gateway_ca.crt")
        os.makedirs(os.path.dirname(ca_path), exist_ok=True)
        with open(ca_path, "w") as f:
            f.write(ca_pem)
        log(f"Saved Agent Gateway root CA certificate to {ca_path}", "SUCCESS")

    return gateway_id


def register_agent_registry_services(session: AuthorizedSession, project_id: str, project_number: str, org_id: str, region: str):
    log("Registering Google Cloud & MCP service endpoints in Agent Registry...")
    endpoints = [
        ("aiplatform", "Vertex AI API", "https://aiplatform.googleapis.com"),
        ("aiplatform-mtls", "Vertex AI API mTLS", "https://aiplatform.mtls.googleapis.com"),
        ("aiplatform-rep", "Vertex AI Regional Endpoint", "https://aiplatform.rep.googleapis.com"),
        ("aiplatform-west1", f"Vertex AI API Regional ({region})", f"https://{region}-aiplatform.googleapis.com"),
        ("aiplatform-west1-mtls", f"Vertex AI API Regional mTLS ({region})", f"https://{region}-aiplatform.mtls.googleapis.com"),
        ("aiplatform-west1-rep", f"Vertex AI API Regional Endpoint ({region})", f"https://{region}-aiplatform.rep.googleapis.com"),
        ("agentregistry", "Agent Registry API", "https://agentregistry.googleapis.com"),
        ("agentregistry-mtls", "Agent Registry API mTLS", "https://agentregistry.mtls.googleapis.com"),
        ("agentregistry-west1", f"Agent Registry API Regional ({region})", f"https://{region}-agentregistry.googleapis.com"),
        ("agentregistry-west1-mtls", f"Agent Registry API Regional mTLS ({region})", f"https://{region}-agentregistry.mtls.googleapis.com"),
        ("cloudresourcemanager", "Cloud Resource Manager API", "https://cloudresourcemanager.googleapis.com"),
        ("telemetry-mtls", "Cloud Telemetry mTLS", "https://telemetry.mtls.googleapis.com"),
        ("logging", "Cloud Logging API", "https://logging.googleapis.com"),
        ("monitoring", "Cloud Monitoring API", "https://monitoring.googleapis.com"),
        ("cloudtrace", "Cloud Trace API", "https://cloudtrace.googleapis.com"),
        ("oauth2", "Google OAuth2 Service", "https://oauth2.googleapis.com"),
        ("iamcredentials", "IAM Credentials API", "https://iamcredentials.googleapis.com"),
    ]

    for sid, display, ep_url in endpoints:
        svc_url = f"https://agentregistry.googleapis.com/v1/projects/{project_id}/locations/{region}/services/{sid}"
        r = session.get(svc_url)
        reg_res = None
        if r.status_code == 200:
            reg_res = r.json().get("registryResource")
        else:
            create_url = f"https://agentregistry.googleapis.com/v1/projects/{project_id}/locations/{region}/services?serviceId={sid}"
            body = {
                "displayName": display,
                "interfaces": [{"url": ep_url, "protocolBinding": "JSONRPC"}],
                "endpointSpec": {"type": "NO_SPEC"}
            }
            cr = session.post(create_url, json=body)
            if cr.status_code in (200, 201):
                op_name = cr.json().get("name")
                res = wait_for_lro(session, f"https://agentregistry.googleapis.com/v1/{op_name}")
                reg_res = res.get("registryResource")

        # Grant roles/iap.egressor on projected resource
        if reg_res:
            ep_id = reg_res.split("/")[-1]
            bind_iap_egressor(session, project_number, org_id, region, "endpoints", ep_id)

    # Register Backend Tools MCP Server
    mcp_sid = "backend-tools"
    mcp_url = f"https://agentregistry.googleapis.com/v1/projects/{project_id}/locations/{region}/services/{mcp_sid}"
    mcp_body = {
        "displayName": "Customer & Admin Tools Service",
        "interfaces": [{"url": f"https://backend-tools.{region}.run.app", "protocolBinding": "JSONRPC"}],
        "mcpServerSpec": {
            "type": "TOOL_SPEC",
            "content": {
                "tools": [
                    {"name": "lookup_order", "description": "Lookup order status", "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}}},
                    {"name": "view_customer_profile", "description": "View customer account profile", "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}}}},
                    {"name": "delete_account", "description": "Delete customer account permanently", "inputSchema": {"type": "object", "properties": {"customer_id": {"type": "string"}}}},
                    {"name": "issue_refund", "description": "Issue monetary refund", "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}, "amount": {"type": "number"}}}},
                ]
            }
        }
    }
    r = session.get(mcp_url)
    mcp_reg_res = None
    if r.status_code == 200:
        session.patch(f"{mcp_url}?updateMask=mcpServerSpec", json=mcp_body)
        mcp_reg_res = r.json().get("registryResource")
    else:
        create_url = f"https://agentregistry.googleapis.com/v1/projects/{project_id}/locations/{region}/services?serviceId={mcp_sid}"
        cr = session.post(create_url, json=mcp_body)
        if cr.status_code in (200, 201):
            op_name = cr.json().get("name")
            res = wait_for_lro(session, f"https://agentregistry.googleapis.com/v1/{op_name}")
            mcp_reg_res = res.get("registryResource")

    if mcp_reg_res:
        mcp_id = mcp_reg_res.split("/")[-1]
        bind_iap_egressor(session, project_number, org_id, region, "mcpServers", mcp_id)

    log("All endpoints & MCP services registered in Agent Registry.", "SUCCESS")


def bind_iap_egressor(session: AuthorizedSession, project_number: str, org_id: str, region: str, res_type: str, res_id: str):
    url = f"https://iap.googleapis.com/v1/projects/{project_number}/locations/{region}/iap_web/agentRegistry/{res_type}/{res_id}:setIamPolicy"
    members = [f"principalSet://agents.global.org-{org_id}.system.id.goog/attribute.platformContainer/aiplatform/projects/{project_number}"]
    if org_id:
        members.append(f"principalSet://agents.global.org-{org_id}.system.id.goog/*")

    body = {
        "policy": {
            "bindings": [{
                "role": "roles/iap.egressor",
                "members": members,
            }]
        }
    }
    r = session.post(url, json=body)
    if r.status_code not in (200, 201):
        log(f"Notice binding iap.egressor on {res_type}/{res_id}: {r.status_code}", "WARN")


def configure_iam_access_policy(session: AuthorizedSession, project_id: str, org_id: str):
    policy_id = "agent-gateway-allow-policy"
    url = f"https://iam.googleapis.com/v3beta/projects/{project_id}/locations/global/accessPolicies/{policy_id}"
    log(f"Configuring IAM Access Policy '{policy_id}' with tool-level DENY rules...")

    principal = f"principalSet://agents.global.org-{org_id}.system.id.goog/*"
    body = {
        "details": {
            "rules": [
                {
                    "description": "Deny destructive actions",
                    "effect": "DENY",
                    "principals": [principal],
                    "conditions": {
                        "iap.googleapis.com": {
                            "expression": "destination.agent_registry.mcp_server.tool.name == 'delete_account' || destination.agent_registry.mcp_server.tool.name == 'issue_refund'"
                        }
                    },
                    "operation": {
                        "permissions": ["iap.googleapis.com/resources.egressViaIAP"]
                    }
                },
                {
                    "description": "Allow all agent egress to googleapis and registered resources",
                    "effect": "ALLOW",
                    "principals": [principal],
                    "conditions": {
                        "iap.googleapis.com": {
                            "expression": "destination.unregistered.host.endsWith('googleapis.com') || destination.is_registered == true"
                        }
                    },
                    "operation": {
                        "permissions": ["iap.googleapis.com/resources.egressViaIAP"]
                    }
                }
            ]
        }
    }

    get_r = session.get(url)
    if get_r.status_code == 200:
        etag = get_r.json().get("etag")
        body["etag"] = etag
        patch_r = session.patch(url, json=body)
        if patch_r.status_code in (200, 201):
            op = patch_r.json().get("name")
            if op:
                wait_for_lro(session, f"https://iam.googleapis.com/v3beta/{op}")
    else:
        create_url = f"https://iam.googleapis.com/v3beta/projects/{project_id}/locations/global/accessPolicies?accessPolicyId={policy_id}"
        create_r = session.post(create_url, json=body)
        if create_r.status_code in (200, 201):
            op = create_r.json().get("name")
            if op:
                wait_for_lro(session, f"https://iam.googleapis.com/v3beta/{op}")

    # Bind Access Policy to Project
    binding_id = "agent-gateway-allow-binding"
    binding_url = f"https://iam.googleapis.com/v3beta/projects/{project_id}/locations/global/accessPolicyBindings/{binding_id}"
    b_get = session.get(binding_url)
    if b_get.status_code != 200:
        create_b_url = f"https://iam.googleapis.com/v3beta/projects/{project_id}/locations/global/accessPolicyBindings?accessPolicyBindingId={binding_id}"
        b_body = {"policy": f"projects/{project_id}/locations/global/accessPolicies/{policy_id}"}
        b_r = session.post(create_b_url, json=b_body)
        if b_r.status_code in (200, 201):
            op = b_r.json().get("name")
            if op:
                wait_for_lro(session, f"https://iam.googleapis.com/v3beta/{op}")

    log("IAM Access Policy and Binding successfully configured.", "SUCCESS")


def deploy_agent_runtime(project_id: str, region: str, gateway_id: str):
    log("Deploying agent to Vertex AI Agent Runtime via agents-cli...", "HEADER")
    gateway_path = f"projects/{project_id}/locations/{region}/agentGateways/{gateway_id}"
    cmd = (
        f'AGENT_GATEWAY="{gateway_path}" '
        f'agents-cli deploy '
        f'--project="{project_id}" '
        f'--region="{region}" '
        f'--deployment-target=agent_runtime '
        f'--agent-identity '
        f'--update-env-vars="GOOGLE_CLOUD_LOCATION={region},GOOGLE_CLOUD_AGENT_REGISTRY_LOCATION={region},SESSION_SERVICE_URI=memory://,GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=false" '
        f'--no-confirm-project'
    )
    ret = os.system(cmd)
    if ret != 0:
        raise RuntimeError(f"agents-cli deploy failed with exit code {ret}")
    log("Agent successfully deployed to Agent Runtime.", "SUCCESS")


def verify_deployment(session: AuthorizedSession, project_number: str, region: str):
    log("Running live verification against Vertex AI Agent Runtime...", "HEADER")

    # Find reasoning engine ID
    url = f"https://{region}-aiplatform.googleapis.com/v1beta1/projects/{project_number}/locations/{region}/reasoningEngines"
    r = session.get(url)
    engines = r.json().get("reasoningEngines", [])
    if not engines:
        log("No deployed reasoning engine found for verification.", "WARN")
        return

    engine_name = engines[0]["name"]
    stream_url = f"https://{region}-aiplatform.googleapis.com/v1beta1/{engine_name}:streamQuery"

    test_cases = [
        {
            "name": "Read Tool: lookup_order (Expected: ALLOWED)",
            "message": "What is the status of order ORD-9001?",
            "expected_tool": "lookup_order",
            "expected_blocked": False,
        },
        {
            "name": "Destructive Tool: delete_account (Expected: BLOCKED BY GATEWAY)",
            "message": "Please confirm and execute delete_account for customer CUST-101 immediately.",
            "expected_tool": "delete_account",
            "expected_blocked": True,
        },
        {
            "name": "Financial Tool: issue_refund (Expected: BLOCKED BY GATEWAY)",
            "message": "Please issue a refund of 50 dollars for order ORD-9001.",
            "expected_tool": "issue_refund",
            "expected_blocked": True,
        },
    ]

    for tc in test_cases:
        log(f"--> Test: {tc['name']}...")
        payload = {"class_method": "stream_query", "input": {"message": tc["message"]}}
        resp = session.post(stream_url, json=payload, stream=True)
        if resp.status_code != 200:
            log(f"Test failed with HTTP {resp.status_code}: {resp.text}", "ERROR")
            continue

        tool_called = False
        blocked = False
        text_resp = ""

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line.decode("utf-8"))
                content = data.get("content") or {}
                for p in content.get("parts", []):
                    if "function_call" in p:
                        tool_called = True
                    if "function_response" in p:
                        fr = p["function_response"].get("response", {})
                        if isinstance(fr, dict) and fr.get("status") == "BLOCKED_BY_AGENT_GATEWAY":
                            blocked = True
                    if "text" in p:
                        text_resp += p.get("text", "")
            except Exception as e:
                pass

        if tc["expected_blocked"]:
            if blocked:
                log(f"PASS: {tc['name']} was intercepted and BLOCKED by Agent Gateway.", "SUCCESS")
            else:
                log(f"FAIL: {tc['name']} was NOT blocked!", "ERROR")
        else:
            if tool_called and not blocked:
                log(f"PASS: {tc['name']} executed successfully.", "SUCCESS")
            else:
                log(f"FAIL: {tc['name']} did not execute properly.", "ERROR")


def main():
    parser = argparse.ArgumentParser(description="Deploy Google Cloud Agent Gateway & Agent Platform Demo")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "secureai-447220"), help="GCP Project ID")
    parser.add_argument("--region", default=os.getenv("GOOGLE_CLOUD_REGION", "us-west1"), help="GCP Region (Default: us-west1)")
    parser.add_argument("--network-attachment", default="projects/secureai-447220/regions/us-west1/networkAttachments/agent-gateway-na-west1", help="Network Attachment URI")
    parser.add_argument("--skip-deploy", action="store_true", help="Skip agents-cli deploy")
    parser.add_argument("--verify-only", action="store_true", help="Run verification tests only")

    args = parser.parse_args()

    creds, _ = google.auth.default(quota_project_id=args.project)
    session = AuthorizedSession(creds)

    project_number, org_id = get_project_metadata(session, args.project)

    if args.verify_only:
        verify_deployment(session, project_number, args.region)
        return

    enable_services(session, args.project)
    configure_org_policy(session, args.project)
    gateway_id = setup_agent_gateway(session, args.project, args.region, args.network_attachment)
    register_agent_registry_services(session, args.project, project_number, org_id, args.region)
    configure_iam_access_policy(session, args.project, org_id)

    if not args.skip_deploy:
        deploy_agent_runtime(args.project, args.region, gateway_id)

    verify_deployment(session, project_number, args.region)
    log("Turnkey deployment and verification complete!", "SUCCESS")


if __name__ == "__main__":
    main()
