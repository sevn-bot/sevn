"""Shared fixtures for the sevn CDP browser engine tests.

Provides a :class:`FakeCDPServer` — an in-process ``websockets`` server that speaks
just enough of the Chrome DevTools Protocol (id-correlated command replies + pushed
events with/without ``sessionId``) to exercise the engine with **no real Chrome**.

Module: tests.browser.conftest
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
import websockets


class FakeCDPServer:
    """An in-process WebSocket server that scripts CDP command replies and events."""

    def __init__(self) -> None:
        """Initialise an empty server (call :meth:`start` to bind a port)."""
        self._server: Any = None
        self._clients: set[Any] = set()
        self._responders: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.received: list[dict[str, Any]] = []
        self.host = "127.0.0.1"
        self.port = 0

    @property
    def ws_url(self) -> str:
        """Return the ``ws://`` URL clients should connect to."""
        return f"ws://{self.host}:{self.port}/devtools/browser/fake"

    def on_command(
        self, method: str, responder: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Register a per-method responder returning the ``result`` object.

        Args:
            method: CDP method to script.
            responder: Callable mapping the raw request message to a ``result`` dict.
        """
        self._responders[method] = responder

    def set_result(self, method: str, result: dict[str, Any]) -> None:
        """Register a static ``result`` for ``method``."""
        self._responders[method] = lambda _msg: result

    async def push_event(
        self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None
    ) -> None:
        """Push a CDP event to all connected clients."""
        message: dict[str, Any] = {"method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        data = json.dumps(message)
        for ws in list(self._clients):
            await ws.send(data)

    async def _handler(self, websocket: Any) -> None:
        self._clients.add(websocket)
        try:
            async for raw in websocket:
                message = json.loads(raw)
                self.received.append(message)
                method = message.get("method", "")
                responder = self._responders.get(method)
                result = responder(message) if responder is not None else {}
                reply: dict[str, Any] = {"id": message["id"], "result": result}
                if isinstance(result, dict) and "__error__" in result:
                    reply = {"id": message["id"], "error": result["__error__"]}
                if message.get("sessionId"):
                    reply["sessionId"] = message["sessionId"]
                await websocket.send(json.dumps(reply))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    async def start(self) -> None:
        """Bind the server to an ephemeral localhost port."""
        self._server = await websockets.serve(self._handler, self.host, 0)
        sock = next(iter(self._server.sockets))
        self.port = sock.getsockname()[1]

    async def stop(self) -> None:
        """Close all clients and the listening socket."""
        for ws in list(self._clients):
            await ws.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def fake_cdp() -> AsyncIterator[FakeCDPServer]:
    """Yield a started :class:`FakeCDPServer`, stopped on teardown."""
    server = FakeCDPServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()
