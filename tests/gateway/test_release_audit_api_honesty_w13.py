"""Batch C W13 — API honesty behavioral regressions (#151, D10).

Contracts: ``GET /capabilities`` channel inventory; OpenAI compat rejects
``stream=true`` with 400; chat completion omits fake ``usage``; turn failures
return non-2xx instead of synthetic success payloads.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from sevn.gateway.api.capabilities_api import register_capabilities_routes
from sevn.gateway.api.openai_compat_api import build_openai_compat_router
from sevn.gateway.session_manager import SessionManager
from sevn.storage.migrate import apply_migrations

_GATEWAY_TOKEN = "required-token-at-least-32-characters-long"
_VALID_STATUSES = frozenset({"implemented", "stub", "unavailable"})
RunTurnFn = Callable[[str, str], Awaitable[None]]


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _capabilities_client() -> TestClient:
    app = FastAPI()
    register_capabilities_routes(app)
    return TestClient(app)


def _openai_compat_client(
    *,
    gateway_token: str | None = _GATEWAY_TOKEN,
    run_turn: RunTurnFn | None = None,
) -> TestClient:
    conn = _memory_conn()
    sessions = SessionManager(conn)
    router_stub = MagicMock()
    if run_turn is not None:
        router_stub._run_turn = run_turn

    app = FastAPI()
    register_capabilities_routes(app)
    app.include_router(build_openai_compat_router())
    app.state.resolved_gateway_token = gateway_token
    app.state.gateway_router = router_stub if run_turn is not None else None
    app.state.sqlite_conn = conn if run_turn is not None else None
    app.state.gateway_sessions = sessions if run_turn is not None else None
    return TestClient(app)


def test_get_capabilities_returns_200_with_channel_inventory() -> None:
    client = _capabilities_client()
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("generated_at"), int)
    channels = body.get("channels")
    assert isinstance(channels, list)
    assert len(channels) >= 2
    for row in channels:
        name = row.get("name")
        assert isinstance(name, str)
        assert name
        label = row.get("label")
        assert isinstance(label, str)
        assert label
        assert row.get("status") in _VALID_STATUSES
        source = row.get("source")
        assert isinstance(source, str)
        assert source
    by_name = {row["name"]: row["status"] for row in channels}
    assert by_name.get("telegram") == "implemented"
    assert by_name.get("webchat") == "implemented"
    assert by_name.get("signal") == "stub"


def test_openai_compat_stream_true_returns_400() -> None:
    client = _openai_compat_client()
    payload: dict[str, Any] = {
        "model": "sevn-agent",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    resp = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
    )
    assert resp.status_code == 400
    assert resp.json().get("detail") == "streaming_not_implemented"


def test_openai_compat_success_omits_usage_key() -> None:
    conn = _memory_conn()
    sessions = SessionManager(conn)

    async def _write_assistant(session_id: str, correlation_id: str) -> None:
        await sessions.add_message(
            session_id,
            role="assistant",
            kind="message",
            content="Hello from sevn",
            visible_to_llm=1,
            status="sent",
            turn_id=correlation_id,
        )

    app = FastAPI()
    register_capabilities_routes(app)
    app.include_router(build_openai_compat_router())
    router_stub = MagicMock()
    router_stub._run_turn = _write_assistant
    app.state.resolved_gateway_token = _GATEWAY_TOKEN
    app.state.gateway_router = router_stub
    app.state.sqlite_conn = conn
    app.state.gateway_sessions = sessions
    client = TestClient(app)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "sevn-agent",
            "messages": [{"role": "user", "content": "ping"}],
        },
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "usage" not in body
    assert body["choices"][0]["message"]["content"] == "Hello from sevn"


def test_openai_compat_turn_error_returns_500_not_fake_success() -> None:
    async def _failing_turn(_session_id: str, _correlation_id: str) -> None:
        raise RuntimeError("turn blew up")

    client = _openai_compat_client(run_turn=_failing_turn)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "sevn-agent",
            "messages": [{"role": "user", "content": "fail please"}],
        },
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
    )
    assert resp.status_code == 500
    assert resp.json().get("detail") == "turn_error"
    assert "choices" not in resp.json()


def test_openai_compat_empty_assistant_reply_returns_500() -> None:
    async def _noop_turn(_session_id: str, _correlation_id: str) -> None:
        return None

    client = _openai_compat_client(run_turn=_noop_turn)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "sevn-agent",
            "messages": [{"role": "user", "content": "silent turn"}],
        },
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
    )
    assert resp.status_code == 500
    assert resp.json().get("detail") == "empty_assistant_reply"
    assert "choices" not in resp.json()
