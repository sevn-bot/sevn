"""OpenAI-compatible HTTP API mount on the sevn gateway.

Module: sevn.gateway.api.openai_compat_api
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

import asyncio
import hashlib
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
_ALLOWED_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


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


def _caller_scope(bearer_token: str) -> tuple[str, str]:
    """Derive authorization scope and user id from the authenticated bearer.

    Args:
        bearer_token (str): Verified gateway bearer secret.

    Returns:
        tuple[str, str]: ``(scope_key, user_id)`` for authorization; each request
            mints a fresh ephemeral session under a unique scope suffix (D17).

    Examples:
        >>> sk1, uid1 = _caller_scope("secret-a")
        >>> sk2, uid2 = _caller_scope("secret-b")
        >>> sk1 == sk2
        False
        >>> _caller_scope("secret-a")[0].startswith('openai_api:')
        True
    """
    digest = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()[:16]
    return f"{_API_CHANNEL}:{digest}", f"openai_api:{digest}"


def _require_bearer(request: Request) -> str:
    """Verify the gateway bearer token and return the submitted secret.

    Args:
        request (Request): Incoming HTTP request.

    Returns:
        str: Verified bearer token.

    Raises:
        HTTPException: When auth is missing, misconfigured, or invalid.

    Examples:
        >>> _require_bearer.__name__
        '_require_bearer'
    """
    gateway_token = getattr(request.app.state, "resolved_gateway_token", None)
    expected = str(gateway_token).strip() if gateway_token else ""
    if not expected:
        raise HTTPException(status_code=503, detail="auth_not_configured")
    from sevn.gateway.auth import extract_bearer, secrets_compare

    submitted = extract_bearer(request.headers.get("Authorization"))
    if submitted is None or not secrets_compare(expected, submitted):
        raise HTTPException(status_code=401, detail="invalid_api_key")
    return submitted


def _reap_ephemeral_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Delete a single-request OpenAI-compat session and its messages (D17).

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Ephemeral session id to remove.

    Returns:
        None

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _reap_ephemeral_session(c, "missing") is None
        True
        >>> c.close()
    """
    conn.execute("DELETE FROM gateway_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM gateway_sessions WHERE session_id = ?", (session_id,))
    conn.commit()


def _last_assistant_text(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    after_message_id: int = 0,
) -> str:
    """Return the most recent visible assistant message for ``session_id``.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Target session id.
        after_message_id (int): Ignore rows at or below this ``gateway_messages.id``.

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
              AND id > ?
            ORDER BY id DESC LIMIT 1
            """,
            (session_id, after_message_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    return str(row[0]) if row else ""


def _max_message_id(conn: sqlite3.Connection, session_id: str) -> int:
    """Return the highest ``gateway_messages.id`` for ``session_id`` (0 when empty).

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Target session id.

    Returns:
        int: Latest row id, or ``0`` when the session has no messages.

    Examples:
        >>> _max_message_id(sqlite3.connect(":memory:"), "missing")
        0
    """
    try:
        row = conn.execute(
            "SELECT MAX(id) FROM gateway_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _clear_visible_messages(conn: sqlite3.Connection, session_id: str) -> None:
    """Remove prior visible LLM history before syncing an OpenAI request batch.

    Args:
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Target session id.

    Returns:
        None: Mutates ``gateway_messages`` in place.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _clear_visible_messages(c, "missing") is None
        True
        >>> c.close()
    """
    conn.execute(
        "DELETE FROM gateway_messages WHERE session_id = ? AND visible_to_llm = 1",
        (session_id,),
    )
    conn.commit()


def _validate_request_messages(messages: list[ChatMessage]) -> None:
    """Reject invalid OpenAI payloads before mutating session history.

    Args:
        messages (list[ChatMessage]): Full OpenAI chat payload.

    Returns:
        None: Raises on invalid input only.

    Raises:
        HTTPException: When roles are unsupported or no user message is present.

    Examples:
        >>> _validate_request_messages([ChatMessage(role="user", content="hi")]) is None
        True
    """
    wrote_user = False
    for msg in messages:
        role = msg.role.strip().lower()
        content = msg.content.strip()
        if not content:
            continue
        if role not in _ALLOWED_MESSAGE_ROLES:
            raise HTTPException(status_code=400, detail=f"unsupported_message_role:{role}")
        if role == "user":
            wrote_user = True
    if not wrote_user:
        raise HTTPException(status_code=400, detail="no_user_message")


async def _sync_request_messages(
    sessions: Any,
    conn: sqlite3.Connection,
    *,
    session_id: str,
    messages: list[ChatMessage],
    correlation_id: str,
) -> None:
    """Replace visible session history with the OpenAI request message sequence.

    Args:
        sessions (Any): :class:`~sevn.gateway.session_manager.SessionManager`.
        conn (sqlite3.Connection): Open gateway SQLite handle.
        session_id (str): Target session id.
        messages (list[ChatMessage]): Full OpenAI chat payload.
        correlation_id (str): Turn correlation id for appended rows.

    Returns:
        None: Writes gateway message rows.

    Raises:
        HTTPException: When no supported role/content pairs are present.

    Examples:
        >>> _sync_request_messages.__name__
        '_sync_request_messages'
    """
    _validate_request_messages(messages)
    for msg in messages:
        role = msg.role.strip().lower()
        content = msg.content.strip()
        if not content:
            continue
        visible_to_llm = 0 if role == "tool" else 1
        await sessions.add_message(
            session_id,
            role=role,
            kind="message",
            content=content,
            visible_to_llm=visible_to_llm,
            status="sent",
            turn_id=correlation_id,
        )


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
    async def list_models(request: Request) -> JSONResponse:
        """List available models (single sevn-agent entry)."""
        _require_bearer(request)
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
    async def health() -> JSONResponse:
        """Return liveness for OpenAI clients (unauthenticated)."""
        return JSONResponse({"status": "ok"})

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
        if body.stream:
            raise HTTPException(status_code=400, detail="streaming_not_implemented")

        submitted = _require_bearer(request)

        router_local = getattr(request.app.state, "gateway_router", None)
        if router_local is None:
            raise HTTPException(status_code=503, detail="gateway_not_ready")

        run_turn = getattr(router_local, "_run_turn", None)
        conn: sqlite3.Connection | None = getattr(request.app.state, "sqlite_conn", None)
        sessions = getattr(request.app.state, "gateway_sessions", None)
        if run_turn is None or conn is None or sessions is None:
            raise HTTPException(status_code=503, detail="gateway_not_ready")

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        correlation_id = str(uuid.uuid4())
        scope_key, user_id = _caller_scope(submitted)
        ephemeral_scope = f"{scope_key}:ephemeral:{uuid.uuid4().hex}"
        session_id = await sessions.ensure_session(
            scope_key=ephemeral_scope,
            channel=_API_CHANNEL,
            user_id=user_id,
        )
        try:
            await _sync_request_messages(
                sessions,
                conn,
                session_id=session_id,
                messages=body.messages,
                correlation_id=correlation_id,
            )
            baseline_message_id = await asyncio.to_thread(_max_message_id, conn, session_id)

            try:
                await asyncio.wait_for(
                    run_turn(session_id, correlation_id),
                    timeout=_TURN_TIMEOUT_S,
                )
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail="turn_timeout") from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=500, detail="turn_error") from exc

            reply = _last_assistant_text(
                conn,
                session_id,
                after_message_id=baseline_message_id,
            )
            if not reply.strip():
                raise HTTPException(status_code=500, detail="empty_assistant_reply")

            return JSONResponse(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": _DEFAULT_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": reply},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
        finally:
            await asyncio.to_thread(_reap_ephemeral_session, conn, session_id)

    return router


def register_openai_compat_routes(app: Any) -> None:
    """Mount OpenAI-compatible routes on ``app``.

    Args:
        app (Any): FastAPI application instance.

    Examples:
        >>> register_openai_compat_routes.__name__
        'register_openai_compat_routes'
    """
    from sevn.gateway.api.capabilities_api import register_capabilities_routes

    register_capabilities_routes(app)
    app.include_router(build_openai_compat_router())
