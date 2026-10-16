"""Loopback MCP echo server (D2). Green after W2.

``with spike_rt.mcp_server.echo_server(session_id) as server`` binds
``127.0.0.1`` on a free port and yields:

- ``url`` — streamable-HTTP endpoint
- ``bearer`` — raw per-session token (not the ``Bearer `` header)
- ``session_id`` — the id passed in, echoed by ``sevn_echo``
- ``calls`` — recorded tool calls with ``name``, ``arguments``, and ``bearer``
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Protocol, cast
from urllib.parse import urlsplit

import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_W2 = pytest.mark.xfail(strict=False, reason="green after W2")


class _Call(Protocol):
    name: str
    arguments: Mapping[str, object]
    bearer: str


class _Server(Protocol):
    url: str
    bearer: str
    session_id: str
    calls: Sequence[_Call]


class _EchoCM(Protocol):
    def __enter__(self) -> _Server: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


def _echo_server() -> Callable[[str], _EchoCM]:
    try:
        from spike_rt.mcp_server import echo_server  # type: ignore[reportMissingImports]
    except ImportError as exc:
        pytest.fail(f"missing spike_rt.mcp_server.echo_server ({exc})")
    return cast(Callable[[str], _EchoCM], echo_server)


def _assert_loopback(url: str) -> None:
    parsed = urlsplit(url)
    assert parsed.scheme == "http"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port not in (None, 0)


@asynccontextmanager
async def _connected(server: _Server) -> AsyncIterator[ClientSession]:
    headers = {"Authorization": f"Bearer {server.bearer}"}
    timeout = httpx2.Timeout(30.0, read=60.0)
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout) as http,
        streamable_http_client(server.url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _open(session_id: str) -> _EchoCM:
    return _echo_server()(session_id)


def _text_schema(schema: object) -> None:
    assert isinstance(schema, dict)
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    text = properties.get("text")
    assert isinstance(text, dict)
    assert text.get("type") == "string"
    required = schema.get("required")
    assert isinstance(required, list)
    assert "text" in required


@_W2
def test_echo_tool_listed() -> None:
    asyncio.run(_echo_tool_listed())


async def _echo_tool_listed() -> None:
    with _open("sess-list") as server:
        bound = server
        assert bound.session_id == "sess-list"
        assert bound.bearer
        _assert_loopback(bound.url)
        async with _connected(bound) as session:
            listed = await session.list_tools()
        names = [tool.name for tool in listed.tools]
        assert names == ["sevn_echo"]
        _text_schema(listed.tools[0].input_schema)


@_W2
def test_echo_returns_session() -> None:
    asyncio.run(_echo_returns_session())


async def _echo_returns_session() -> None:
    with _open("sess-echo") as server:
        async with _connected(server) as session:
            result = await session.call_tool("sevn_echo", {"text": "ping"})
        assert result.is_error is not True
        payload = _echo_payload(result)
        assert payload["echo"] == "ping"
        assert payload["session"] == "sess-echo"
        assert len(server.calls) == 1
        recorded = server.calls[0]
        assert recorded.name == "sevn_echo"
        assert recorded.arguments["text"] == "ping"
        assert recorded.bearer == server.bearer


@_W2
def test_wrong_bearer_401() -> None:
    wrong = secrets.token_urlsafe(32)
    with _open("sess-a") as first, _open("sess-b") as second:
        assert first.session_id == "sess-a"
        assert second.session_id == "sess-b"
        assert first.bearer
        assert first.bearer != second.bearer
        assert first.url != second.url
        assert wrong != first.bearer
        _assert_loopback(first.url)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "spike-test", "version": "0"},
                },
            }
        ).encode()
        headers = {
            "Authorization": f"Bearer {wrong}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        with httpx2.Client(timeout=10.0) as client:
            response = client.post(first.url, content=body, headers=headers)
        assert response.status_code == 401
        assert first.bearer.encode() not in response.content
        assert second.bearer.encode() not in response.content


def _echo_payload(result: object) -> dict[str, str]:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        parsed = _as_echo(structured)
        if parsed is not None:
            return parsed
    for block in getattr(result, "content", ()):
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            parsed = _as_echo(decoded)
            if parsed is not None:
                return parsed
    pytest.fail("sevn_echo result did not include string fields echo and session")


def _as_echo(payload: dict[object, object]) -> dict[str, str] | None:
    echo = payload.get("echo")
    session = payload.get("session")
    if isinstance(echo, str) and isinstance(session, str):
        return {"echo": echo, "session": session}
    return None
