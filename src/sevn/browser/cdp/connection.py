"""Browser-level CDP WebSocket connection: command correlation + event bus.

One :class:`CDPConnection` owns a single WebSocket to Chrome's browser endpoint
(``ws://.../devtools/browser/<id>``). Page/iframe targets are reached over the same
socket via flattened ``Target.setAutoAttach`` ``sessionId`` routing — no per-tab
sockets. Commands are correlated by a monotonic integer ``id``; events are demuxed by
``sessionId`` (absent ⇒ browser-level).

Module: sevn.browser.cdp.connection
Depends: asyncio, contextlib, itertools, json, sevn.browser.cdp.protocol

Exports:
    CDPConnection — connect, send, on/wait_for, close.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(CDPConnection.send)
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

from sevn.browser.cdp.protocol import CDPError

_DEFAULT_TIMEOUT: Final[float] = 30.0
# Chrome DOM/screenshot payloads exceed the 1 MiB websockets default; lift the cap.
_MAX_WS_SIZE: Final[int] = 256 * 1024 * 1024

EventCallback = Callable[[dict[str, Any]], None | Awaitable[None]]


class CDPConnection:
    """A single browser-level CDP WebSocket with id/Future command correlation.

    Never closes the operator's Chrome — :meth:`close` only drops the WebSocket.
    """

    def __init__(self, ws: Any, ws_url: str) -> None:
        """Bind a connected WebSocket and start the background reader.

        Args:
            ws (Any): Connected ``websockets`` client (awaitable ``send``/``recv``).
            ws_url (str): The ``ws://`` browser debugger URL (for diagnostics).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPConnection.__init__)
            True
        """
        self._ws = ws
        self._ws_url = ws_url
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        # listeners keyed by method name; "*" receives every event.
        self._listeners: dict[str, list[EventCallback]] = {}
        self._waiters: list[
            tuple[asyncio.Future[dict[str, Any]], Callable[[dict[str, Any]], bool]]
        ] = []
        self._closed = False
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._reader: asyncio.Task[None] = asyncio.ensure_future(self._read_loop())

    @property
    def ws_url(self) -> str:
        """Return the browser debugger WebSocket URL.

        Returns:
            str: The ``ws://`` URL this connection was opened against.

        Examples:
            >>> import inspect
            >>> isinstance(CDPConnection.ws_url, property)
            True
        """
        return self._ws_url

    @property
    def closed(self) -> bool:
        """Return whether the connection has been closed.

        Returns:
            bool: ``True`` after :meth:`close` or a dropped socket.

        Examples:
            >>> import inspect
            >>> isinstance(CDPConnection.closed, property)
            True
        """
        return self._closed

    @classmethod
    async def connect(cls, ws_url: str) -> CDPConnection:
        """Open a WebSocket to ``ws_url`` and return a started connection.

        Args:
            ws_url (str): Browser debugger URL from ``/json/version``.

        Returns:
            CDPConnection: Connected, reading connection.

        Raises:
            ImportError: When the optional ``websockets`` dependency is missing.
            RuntimeError: When the socket cannot be opened.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPConnection.connect)
            True
        """
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - guarded by HAS_CDP
            msg = "websockets not installed — run: uv sync --extra browser-cdp"
            raise ImportError(msg) from exc
        try:
            ws = await websockets.connect(ws_url, max_size=_MAX_WS_SIZE)
        except Exception as exc:
            msg = f"failed to open CDP WebSocket {ws_url}: {exc}"
            raise RuntimeError(msg) from exc
        return cls(ws, ws_url)

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a CDP command and await its correlated reply ``result``.

        Args:
            method (str): CDP method, for example ``Page.navigate``.
            params (dict[str, Any] | None): Method params.
            session_id (str | None): Target session id (flattened routing); ``None`` ⇒ browser-level.
            timeout (float): Seconds to await the reply.

        Returns:
            dict[str, Any]: The ``result`` object from Chrome.

        Raises:
            CDPError: When Chrome returns an ``error`` reply.
            RuntimeError: When the connection is closed.
            TimeoutError: When no reply arrives within ``timeout``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPConnection.send)
            True
        """
        if self._closed:
            msg = "CDP connection is closed"
            raise RuntimeError(msg)
        msg_id = next(self._ids)
        payload: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[msg_id] = fut
        try:
            await self._ws.send(json.dumps(payload))
            reply = await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            self._pending.pop(msg_id, None)
            msg = f"CDP command timed out after {timeout}s: {method}"
            raise TimeoutError(msg) from None
        finally:
            self._pending.pop(msg_id, None)
        if "error" in reply:
            err = reply["error"] or {}
            raise CDPError(
                method,
                code=err.get("code"),
                message=str(err.get("message") or ""),
                data=err.get("data"),
            )
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def on(self, method: str, callback: EventCallback) -> Callable[[], None]:
        """Register an event listener for ``method`` (use ``"*"`` for all events).

        Args:
            method (str): CDP event method, for example ``Target.attachedToTarget``.
            callback (EventCallback): Sync or async callable receiving the raw message.

        Returns:
            Callable[[], None]: A disposer that removes the listener.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPConnection.on)
            True
        """
        self._listeners.setdefault(method, []).append(callback)

        def _dispose() -> None:
            handlers = self._listeners.get(method)
            if handlers and callback in handlers:
                handlers.remove(callback)

        return _dispose

    async def wait_for(
        self,
        method: str,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for the next ``method`` event matching ``predicate``.

        Args:
            method (str): CDP event method to await.
            predicate (Callable[[dict[str, Any]], bool] | None): Extra filter on the message.
            timeout (float): Seconds before raising :class:`TimeoutError`.
            session_id (str | None): Require this originating ``sessionId`` when set.

        Returns:
            dict[str, Any]: The matching raw event message.

        Raises:
            TimeoutError: When no matching event arrives in time.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPConnection.wait_for)
            True
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()

        def _match(message: dict[str, Any]) -> bool:
            if message.get("method") != method:
                return False
            if session_id is not None and message.get("sessionId") != session_id:
                return False
            return predicate(message) if predicate is not None else True

        entry = (fut, _match)
        self._waiters.append(entry)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            msg = f"timed out after {timeout}s waiting for CDP event: {method}"
            raise TimeoutError(msg) from None
        finally:
            with contextlib.suppress(ValueError):
                self._waiters.remove(entry)

    async def _read_loop(self) -> None:
        """Background task: read frames, resolve replies, dispatch events.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPConnection._read_loop)
            True
        """
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(message, dict):
                    continue
                msg_id = message.get("id")
                if isinstance(msg_id, int):
                    fut = self._pending.get(msg_id)
                    if fut is not None and not fut.done():
                        fut.set_result(message)
                    continue
                self._dispatch_event(message)
        except asyncio.CancelledError:
            raise
        except Exception:  # nosec B110 — reader task exits when the socket closes
            pass
        finally:
            self._fail_pending()

    def _dispatch_event(self, message: dict[str, Any]) -> None:
        """Deliver an event message to one-shot waiters and registered listeners.

        Args:
            message (dict[str, Any]): Raw CDP event message (``method``/``params``/``sessionId``).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPConnection._dispatch_event)
            True
        """
        for fut, match in list(self._waiters):
            if not fut.done() and match(message):
                fut.set_result(message)
        method = message.get("method")
        callbacks = list(self._listeners.get(str(method), ())) + list(self._listeners.get("*", ()))
        for cb in callbacks:
            try:
                result = cb(message)
                if asyncio.iscoroutine(result):
                    task = asyncio.ensure_future(result)
                    self._bg_tasks.add(task)
                    task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # nosec B112 — one bad handler must not stop event demux
                continue

    def _fail_pending(self) -> None:
        """Reject outstanding command futures/waiters after the socket drops.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPConnection._fail_pending)
            True
        """
        self._closed = True
        exc = RuntimeError("CDP connection closed")
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        for fut, _match in list(self._waiters):
            if not fut.done():
                fut.set_exception(exc)
        self._waiters.clear()

    async def close(self) -> None:
        """Close the WebSocket and stop the reader (never closes Chrome itself).

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPConnection.close)
            True
        """
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._ws.close()
        if not self._reader.done():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        self._fail_pending()


__all__ = ["CDPConnection"]
