"""
Google Cloud Agent Platform: ADK Agent with Native Agent Gateway & Agent Identity.
"""

import os
import socket

_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if family == 0 or family == socket.AF_UNSPEC:
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv4_getaddrinfo

try:
    import vertexai.agent_engines.templates.adk as _adk_tmpl
    _adk_tmpl._warn_if_telemetry_api_disabled = lambda: None
except Exception:
    pass

import ssl
import certifi

ca_cert_path = os.path.join(os.path.dirname(__file__), "agent_gateway_ca.crt")
if os.path.exists(ca_cert_path):
    combined_ca_path = "/tmp/combined_agent_gateway_ca.crt"
    try:
        with open(combined_ca_path, "w") as out_f:
            with open(certifi.where(), "r") as certifi_f:
                out_f.write(certifi_f.read())
            out_f.write("\n")
            with open(ca_cert_path, "r") as ca_f:
                out_f.write(ca_f.read())
        os.environ["SSL_CERT_FILE"] = combined_ca_path
        os.environ["REQUESTS_CA_BUNDLE"] = combined_ca_path
        os.environ["CURL_CA_BUNDLE"] = combined_ca_path
    except Exception as e:
        print(f"Warning: Failed to setup combined CA: {e}")

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

try:
    from app.mcp_server.tools import (
        lookup_order,
        view_customer_profile,
        issue_refund,
        delete_account,
    )
except ImportError:
    from mcp_server.tools import (
        lookup_order,
        view_customer_profile,
        issue_refund,
        delete_account,
    )

MODEL = "gemini-2.5-flash"
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "secureai-447220")
REGION = (
    os.getenv("GOOGLE_CLOUD_LOCATION")
    if os.getenv("GOOGLE_CLOUD_LOCATION") and os.getenv("GOOGLE_CLOUD_LOCATION") != "global"
    else (os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or "us-west1")
)

os.environ["GOOGLE_CLOUD_LOCATION"] = REGION
os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID

INSTRUCTION = """You are a customer service support agent deployed on Google Cloud Agent Platform.
You assist customers with looking up order details and reviewing customer profiles.
Only perform actions that are requested, and assist users clearly and politely.
"""

from google.genai import Client

genai_client = Client(
    vertexai=True,
    project=PROJECT_ID,
    location=REGION,
)

root_agent = Agent(
    name="support_agent",
    model=Gemini(
        model=MODEL,
        client=genai_client,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=INSTRUCTION,
    tools=[lookup_order, view_customer_profile, issue_refund, delete_account],
)

app = App(
    root_agent=root_agent,
    name="agent-gateway-iam-demo",
)
