"""Serve the reasoning_engine {class_method, input} contract over HTTP.

Guarantees support for Vertex AI Console Playground and Gemini Enterprise.
Agent Engine forwards calls to /api/reasoning_engine and /api/stream_reasoning_engine.
"""

import inspect
import json
import logging

from fastapi import FastAPI, HTTPException, Request, encoders, responses
from vertexai.agent_engines.templates.adk import AdkApp

from app.app_utils import services

logger = logging.getLogger(__name__)


def _no_op_instrumentor_builder(project_id: str) -> None:
    """No-op so set_up() keeps the startup instrumentor and generate_content spans."""
    return None


def attach_reasoning_engine_routes(app: FastAPI) -> None:
    """Register reasoning_engine routes that dispatch to an AdkApp."""
    runtime: AdkApp | None = None
    streaming_methods: set[str] = set()
    sync_methods: set[str] = set()

    def get_runtime() -> AdkApp:
        nonlocal runtime, streaming_methods, sync_methods
        if runtime is None:
            from app.agent import app as adk_app

            runtime = AdkApp(
                app=adk_app,
                session_service_builder=services.get_session_service,
                artifact_service_builder=services.get_artifact_service,
                instrumentor_builder=_no_op_instrumentor_builder,
            )
            runtime.set_up()
            operations = runtime.register_operations()
            streaming_methods = set(operations.get("stream", [])) | set(
                operations.get("async_stream", [])
            )
            sync_methods = set(operations.get("", [])) | set(
                operations.get("async", [])
            )
            logger.info(
                "Reasoning Engine routes initialized. Streaming methods: %s, Sync methods: %s",
                streaming_methods,
                sync_methods,
            )
        return runtime

    def resolve_method(class_method: str, *, streaming: bool):
        rt = get_runtime()
        # Prefer native async methods inside ASGI server to preserve event loop lifecycle
        if streaming and class_method in ("stream_query", "async_stream_query"):
            return getattr(rt, "async_stream_query")
        if not streaming and class_method in ("query", "async_query"):
            return getattr(rt, "async_query")

        allowed = streaming_methods if streaming else sync_methods
        if class_method not in allowed:
            raise HTTPException(
                status_code=404,
                detail=f"Unsupported reasoning_engine method: {class_method!r}",
            )
        return getattr(rt, class_method)

    @app.post("/api/stream_reasoning_engine")
    @app.post("/stream_reasoning_engine")
    async def stream_query(request: Request) -> responses.StreamingResponse:
        body = await request.json()
        class_method = body.get("class_method", "stream_query")
        kwargs = dict(body.get("input") or {})
        if "user_id" not in kwargs:
            kwargs["user_id"] = "playground-user"

        method = resolve_method(class_method, streaming=True)

        async def generator():
            res = method(**kwargs)
            if inspect.iscoroutine(res):
                res = await res
            if hasattr(res, "__aiter__"):
                async for event in res:
                    yield json.dumps(encoders.jsonable_encoder(event)) + "\n"
            else:
                for event in res:
                    yield json.dumps(encoders.jsonable_encoder(event)) + "\n"

        return responses.StreamingResponse(
            content=generator(), media_type="application/json"
        )

    @app.post("/api/reasoning_engine")
    @app.post("/reasoning_engine")
    async def query(request: Request) -> responses.JSONResponse:
        body = await request.json()
        class_method = body.get("class_method", "query")
        kwargs = dict(body.get("input") or {})
        if "user_id" not in kwargs:
            kwargs["user_id"] = "playground-user"

        rt = get_runtime()
        if class_method in ("query", "stream_query", "async_query", "async_stream_query"):
            events = []
            async for ev in rt.async_stream_query(**kwargs):
                events.append(ev)
            return responses.JSONResponse(
                content=encoders.jsonable_encoder({"output": events})
            )

        method = resolve_method(class_method, streaming=False)
        output = (
            await method(**kwargs)
            if inspect.iscoroutinefunction(method)
            else method(**kwargs)
        )
        return responses.JSONResponse(
            content=encoders.jsonable_encoder({"output": output})
        )
