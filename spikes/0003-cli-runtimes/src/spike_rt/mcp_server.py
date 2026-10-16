"""Loopback streamable-HTTP MCP server with one ``sevn_echo`` tool (D2)."""

from __future__ import annotations

import asyncio
import secrets
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import uvicorn
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

_START_TIMEOUT_S = 10.0


@dataclass
class RecordedCall:
    """One ``sevn_echo`` invocation observed by the server."""

    name: str
    arguments: dict[str, object]
    bearer: str


@dataclass
class BoundServer:
    """A running echo server. ``bearer`` is the raw token, without the scheme."""

    url: str
    bearer: str
    session_id: str
    calls: list[RecordedCall] = field(default_factory=list)


class _ThreadServer(uvicorn.Server):
    """Uvicorn server that does not install process signal handlers.

    The echo server runs on a background thread. ``signal.signal`` is only
    legal on the main thread, so the stock ``serve`` wrapper cannot start there.
    """

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        await self._serve(sockets)


class _BearerVerifier:
    """Accept exactly one raw bearer token."""

    def __init__(self, bearer: str) -> None:
        self._bearer = bearer

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._bearer):
            return None
        return AccessToken(token=token, client_id="sevn-spike", scopes=[])


@contextmanager
def echo_server(session_id: str) -> Iterator[BoundServer]:
    """Bind ``127.0.0.1`` on a free port and serve ``sevn_echo`` until exit."""

    bearer = secrets.token_urlsafe(32)
    bound = BoundServer(url="", bearer=bearer, session_id=session_id)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    thread: threading.Thread | None = None
    server: _ThreadServer | None = None
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}/mcp"
        bound.url = url
        app = _build_app(bound, url)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        server = _ThreadServer(config)
        errors: list[BaseException] = []

        def _run() -> None:
            try:
                asyncio.run(server.serve(sockets=[sock]))
            except (Exception, SystemExit) as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=_run, name=f"sevn-echo-{port}", daemon=True)
        thread.start()
        _wait_until_started(server, thread, errors)
        yield bound
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        sock.close()


def _build_app(bound: BoundServer, url: str) -> object:
    server = MCPServer(
        "sevn-echo",
        log_level="WARNING",
        auth=AuthSettings(
            issuer_url="http://127.0.0.1",
            resource_server_url=url,  # type: ignore[arg-type]
            validate_token_resource=False,
        ),
        token_verifier=_BearerVerifier(bound.bearer),
    )

    @server.tool(name="sevn_echo", description="Echo text and the sevn session id.")
    async def sevn_echo(text: str) -> dict[str, str]:
        access = get_access_token()
        presented = access.token if access is not None else bound.bearer
        bound.calls.append(
            RecordedCall(name="sevn_echo", arguments={"text": text}, bearer=presented)
        )
        return {"echo": text, "session": bound.session_id}

    return server.streamable_http_app(host="127.0.0.1")


def _wait_until_started(
    server: _ThreadServer,
    thread: threading.Thread,
    errors: list[BaseException],
) -> None:
    deadline = time.monotonic() + _START_TIMEOUT_S
    while not server.started:
        if errors:
            raise RuntimeError("echo server failed to start") from errors[0]
        if not thread.is_alive():
            raise RuntimeError("echo server stopped before listening")
        if time.monotonic() > deadline:
            raise RuntimeError("echo server did not start")
        time.sleep(0.02)
