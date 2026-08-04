"""Batch D W14 RED — OpenAI-compat concurrency & auth (#174; green after W16).

Contracts: concurrent same-bearer completions are isolated (D17); ``GET /v1/models``
requires bearer (D18); unknown models normalize to ``sevn-agent`` (D19).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from sevn.gateway.api.capabilities_api import register_capabilities_routes
from sevn.gateway.api.openai_compat_api import _DEFAULT_MODEL, build_openai_compat_router
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations

_GATEWAY_TOKEN = "required-token-at-least-32-characters-long"
RunTurnFn = Callable[[str, str], Awaitable[None]]


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _openai_compat_client(*, run_turn: RunTurnFn) -> tuple[TestClient, sqlite3.Connection]:
    conn = _memory_conn()
    sessions = SessionManager(conn)
    router_stub = MagicMock()
    router_stub._run_turn = run_turn

    app = FastAPI()
    register_capabilities_routes(app)
    app.include_router(build_openai_compat_router())
    app.state.resolved_gateway_token = _GATEWAY_TOKEN
    app.state.gateway_router = router_stub
    app.state.sqlite_conn = conn
    app.state.gateway_sessions = sessions
    return TestClient(app), conn


@pytest.mark.xfail(reason="green after W16: concurrent same-bearer isolation", strict=False)
def test_concurrent_same_bearer_completions_isolated_replies() -> None:
    """W14.4: two concurrent same-bearer requests each get their own correct reply."""
    conn_holder: dict[str, sqlite3.Connection] = {}

    async def _echo_user_assistant(session_id: str, correlation_id: str) -> None:
        conn = conn_holder["conn"]
        await asyncio.sleep(0.05)
        row = conn.execute(
            """
            SELECT content FROM gateway_messages
            WHERE session_id = ? AND role = 'user' AND visible_to_llm = 1
            ORDER BY id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        user_text = str(row[0]) if row else ""
        sessions = SessionManager(conn)
        await sessions.add_message(
            session_id,
            role="assistant",
            kind="message",
            content=f"echo:{user_text}",
            visible_to_llm=1,
            status="sent",
            turn_id=correlation_id,
        )

    client, conn = _openai_compat_client(run_turn=_echo_user_assistant)
    conn_holder["conn"] = conn
    headers = {"Authorization": f"Bearer {_GATEWAY_TOKEN}"}

    def _post(user_content: str) -> Any:
        return client.post(
            "/v1/chat/completions",
            json={
                "model": _DEFAULT_MODEL,
                "messages": [{"role": "user", "content": user_content}],
            },
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_post, "message-A")
        future_b = pool.submit(_post, "message-B")
        resp_a = future_a.result()
        resp_b = future_b.result()

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    body_a = resp_a.json()
    body_b = resp_b.json()
    assert body_a["choices"][0]["message"]["content"] == "echo:message-A"
    assert body_b["choices"][0]["message"]["content"] == "echo:message-B"


def _bare_openai_client() -> TestClient:
    app = FastAPI()
    register_capabilities_routes(app)
    app.include_router(build_openai_compat_router())
    app.state.resolved_gateway_token = _GATEWAY_TOKEN
    app.state.gateway_router = MagicMock()
    app.state.sqlite_conn = _memory_conn()
    app.state.gateway_sessions = SessionManager(app.state.sqlite_conn)
    return TestClient(app)


@pytest.mark.xfail(reason="green after W16: /v1/models bearer gate", strict=False)
def test_v1_models_requires_bearer_401_without() -> None:
    """W14.5 (D18): ``GET /v1/models`` rejects unauthenticated callers with 401."""
    client = _bare_openai_client()
    resp = client.get("/v1/models")
    assert resp.status_code == 401
    assert resp.json().get("detail") == "invalid_api_key"


@pytest.mark.xfail(reason="green after W16: /v1/health liveness-only body", strict=False)
def test_v1_health_public_returns_status_ok_only() -> None:
    """W14.5 (D18): ``GET /v1/health`` stays public and omits internal gateway fields."""
    client = _bare_openai_client()
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.xfail(reason="green after W16: model echo normalization", strict=False)
def test_unknown_model_normalized_to_default_in_response() -> None:
    """W14.6 (D19): response ``model`` is always ``sevn-agent`` regardless of request."""
    conn = _memory_conn()
    sessions = SessionManager(conn)

    async def _write_assistant(session_id: str, correlation_id: str) -> None:
        await sessions.add_message(
            session_id,
            role="assistant",
            kind="message",
            content="normalized-model-ok",
            visible_to_llm=1,
            status="sent",
            turn_id=correlation_id,
        )

    client, _ = _openai_compat_client(run_turn=_write_assistant)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
        },
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == _DEFAULT_MODEL
