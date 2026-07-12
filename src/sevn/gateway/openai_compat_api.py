"""OpenAI-compatible HTTP API mount on the sevn gateway.

Module: sevn.gateway.openai_compat_api
Depends: fastapi, pydantic, sqlite3, sevn.gateway.session_manager

Exposes:
  GET  /v1/models            — list available models (sevn-agent)
  POST /v1/chat/completions  — OpenAI Chat Completions format; dispatches to
                               the gateway agent turn spine and awaits the reply
  GET  /health               — lightweight liveness probe

Any OpenAI-compatible frontend (Open WebUI, LobeChat, LibreChat, etc.) can
connect by pointing at ``http://host:port/v1`` and authenticating with the
gateway bearer token (``Authorization: Bearer <token>``).

Exports:
    ChatMessage — one OpenAI chat message.
    ChatCompletionRequest — minimal chat completions request body.
    build_openai_compat_router — ``/v1`` APIRouter factory.
    register_openai_compat_routes — mount router on a FastAPI app.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

JsonDict = dict[str, Any]

_DEFAULT_MODEL = "sevn-agent"
_TURN_TIMEOUT_S = 120
_API_CHANNEL = "openai_api"


class ChatMessage(BaseModel):
    """One OpenAI chat message.

    Examples:
        >>> ChatMessage(role="user", content="hi").role
        'user'
    """

    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    """Minimal OpenAI chat completions request body.

    Examples:
        >>> ChatCompletionRequest(messages=[]).model
        'sevn-agent'
    """

    model: str = _DEFAULT_MODEL
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False


def _last_assistant_text(conn: sqlite3.Connection, session_id: str) -> str:
    """Return the most recent visible assistant message for ``session_id``.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Target session id.

    Returns:
        str: Assistant message content, or empty string when absent.

    Examples:
        >>> _last_assistant_text(sqlite3.connect(":memory:"), "missing")
        ''
    """
    try:
        row = conn.execute(
            """
            SELECT content FROM gateway_messages
            WHERE session_id = ? AND role = 'assistant' AND visible_to_llm = 1
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return str(row[0]) if row else ""


def build_openai_compat_router() -> APIRouter:
    """Return router for OpenAI-compatible clients (Open WebUI, LobeChat, etc.).

    Returns:
        APIRouter: Mounted at ``/v1`` by :func:`register_openai_compat_routes`.

    Examples:
        >>> r = build_openai_compat_router()
        >>> r.prefix
        '/v1'
    """
    router = APIRouter(prefix="/v1", tags=["openai-compat"])

    @router.get("/models")
    async def list_models() -> JSONResponse:
        """List available models (single sevn-agent entry)."""
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {
                        "id": _DEFAULT_MODEL,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "sevn",
                    }
                ],
            }
        )

    @router.get("/health")
    async def health(request: Request) -> JSONResponse:
        """Return gateway readiness for OpenAI clients."""
        router_local = getattr(request.app.state, "gateway_router", None)
        return JSONResponse({"status": "ok", "gateway": router_local is not None})

    @router.post("/chat/completions")
    async def chat_completions(
        body: ChatCompletionRequest,
        request: Request,
    ) -> JSONResponse:
        """Dispatch user prompt to the gateway agent turn and return the reply.

        Authenticates via the gateway bearer token when configured. Dispatches
        directly to :func:`~sevn.gateway.agent_turn.build_agent_run_turn`'s
        ``RunTurnFn`` and reads the assistant reply from SQLite after the turn.
        """
        gateway_token = getattr(request.app.state, "resolved_gateway_token", None)
        if gateway_token:
            auth = request.headers.get("Authorization", "")
            bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
            if bearer != str(gateway_token).strip():
                raise HTTPException(status_code=401, detail="invalid_api_key")

        router_local = getattr(request.app.state, "gateway_router", None)
        if router_local is None:
            raise HTTPException(status_code=503, detail="gateway_not_ready")

        user_text = ""
        for msg in reversed(body.messages):
            if msg.role == "user" and msg.content.strip():
                user_text = msg.content.strip()
                break
        if not user_text:
            raise HTTPException(status_code=400, detail="no_user_message")

        run_turn = getattr(router_local, "_run_turn", None)
        conn: sqlite3.Connection | None = getattr(request.app.state, "sqlite_conn", None)
        sessions = getattr(request.app.state, "gateway_sessions", None)

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        reply = ""

        if run_turn is not None and conn is not None and sessions is not None:
            correlation_id = str(uuid.uuid4())
            session_id = await sessions.ensure_session(
                scope_key=f"{_API_CHANNEL}:default",
                channel=_API_CHANNEL,
                user_id="openai_api",
            )
            await sessions.add_message(
                session_id,
                role="user",
                kind="message",
                content=user_text,
                visible_to_llm=1,
                status="sent",
                turn_id=correlation_id,
            )
            try:
                import asyncio

                await asyncio.wait_for(
                    run_turn(session_id, correlation_id),
                    timeout=_TURN_TIMEOUT_S,
                )
                reply = _last_assistant_text(conn, session_id)
            except TimeoutError:
                reply = "[turn timed out]"
            except Exception:
                reply = "[turn error — see gateway logs]"
        else:
            reply = (
                "OpenAI-compatible gateway mounted; runtime not wired "
                "(start the full gateway to enable agent dispatch)."
            )

        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.model or _DEFAULT_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    return router


def register_openai_compat_routes(app: Any) -> None:
    """Mount OpenAI-compatible routes on ``app``.

    Args:
        app (Any): FastAPI application instance.

    Examples:
        >>> register_openai_compat_routes.__name__
        'register_openai_compat_routes'
    """
    app.include_router(build_openai_compat_router())
