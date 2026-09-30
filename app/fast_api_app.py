"""FastAPI application serving ADK Agent with Agent Gateway."""

import contextlib
import os
from collections.abc import AsyncIterator

import google.auth
from a2a.server.tasks import InMemoryTaskStore
from dotenv import load_dotenv
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app, NestedAgentLoader
from google.adk.runners import Runner

from app.app_utils import services
from app.app_utils.a2a import attach_a2a_routes
from app.app_utils.typing import Feedback

load_dotenv()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AliasedAgentLoader(NestedAgentLoader):
    """Loader ensuring both 'app' and the deployed engine display name 'agent-gateway-iam-demo' resolve."""

    def list_agents(self) -> list[str]:
        agents = super().list_agents()
        for alias in ["agent-gateway-iam-demo", "agent_gateway_iam_demo", "app"]:
            if alias not in agents:
                agents.append(alias)
        return agents

    def load_agent(self, agent_name: str):
        if agent_name in ("agent-gateway-iam-demo", "agent_gateway_iam_demo"):
            return super().load_agent("app")
        return super().load_agent(agent_name)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app
    from app.agent import root_agent

    runner = Runner(
        app=adk_app,
        session_service=services.get_session_service(),
        artifact_service=services.get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    await attach_a2a_routes(
        app,
        agent=root_agent,
        runner=runner,
        task_store=InMemoryTaskStore(),
        rpc_path=f"/a2a/{adk_app.name}",
    )
    if adk_app.name != "agent-gateway-iam-demo":
        await attach_a2a_routes(
            app,
            agent=root_agent,
            runner=runner,
            task_store=InMemoryTaskStore(),
            rpc_path="/a2a/agent-gateway-iam-demo",
        )
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    agent_loader=AliasedAgentLoader(AGENT_DIR),
    web=True,
    artifact_service_uri=services.ARTIFACT_SERVICE_URI,
    allow_origins=allow_origins,
    session_service_uri=services.SESSION_SERVICE_URI,
    otel_to_cloud=False,
    lifespan=lifespan,
)
app.title = "agent-gateway-iam-demo"
app.description = "ADK Agent Platform Demo with Agent Gateway and Agent Identity"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    return {"status": "success"}


from app.app_utils.reasoning_engine_adapter import attach_reasoning_engine_routes

attach_reasoning_engine_routes(app)


@app.get("/healthz")
def healthz():
    return {"status": "healthy", "service": "agent-gateway-iam-demo"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
