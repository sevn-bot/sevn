"""Web UI WebSocket connection registry (`specs/19-channel-webui.md` §3.2, §4.3).
Module: sevn.gateway.api.web_transport
Depends: asyncio, fastapi.WebSocket, logging
Exports:
    WebSocketLike — duck-typed WebSocket protocol used in tests.
    WebChannelTransport — ``session_id``-keyed connection registry with fan-out.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from loguru import logger


class WebSocketLike(Protocol):
    """Subset of :class:`fastapi.WebSocket` used by :class:`WebChannelTransport`.
    Lets unit tests inject lightweight fakes without standing up a Starlette
    ASGI scope.
    """

    async def send_text(self, data: str) -> None:
        """Send a UTF-8 text frame.
        Args:
            data (str): JSON-encoded frame.
        Returns:
            None: Awaited only for side effects.
        Examples:
            >>> isinstance(WebSocketLike, type)
            True
        """
        ...


class WebChannelTransport:
    """Track active WebSocket clients per ``session_id`` (`specs/19-channel-webui.md` §3.2).
    The transport is ephemeral and process-local. ``register`` stores the
    ``(session_id, client_id)`` tuple under both the session-id fan-out map
    and the client-id lookup. ``unregister`` is idempotent and survives
    disconnects mid-flight. ``send_to_session`` swallows individual peer
    failures (and unregisters dead peers) without raising to the caller.
    Examples:
        >>> import asyncio
        >>> class _Echo:
        ...     def __init__(self) -> None:
        ...         self.sent: list[str] = []
        ...     async def send_text(self, data: str) -> None:
        ...         self.sent.append(data)
        >>> t = WebChannelTransport()
        >>> ws = _Echo()
        >>> asyncio.run(t.register(session_id="s1", client_id="c1", ws=ws))
        >>> asyncio.run(t.send_to_session("s1", '{"hi": 1}'))
        1
        >>> ws.sent
        ['{"hi": 1}']
    """

    def __init__(self) -> None:
        """Initialise the empty connection registry.
        Examples:
            >>> WebChannelTransport().session_count("none")
            0
        """
        self._lock = asyncio.Lock()
        self._by_session: dict[str, dict[str, WebSocketLike]] = {}
        self._by_client: dict[str, tuple[str, WebSocketLike]] = {}

    async def register(
        self,
        *,
        session_id: str,
        client_id: str,
        ws: WebSocketLike,
    ) -> None:
        """Register ``ws`` under ``(session_id, client_id)``.
        Args:
            session_id (str): Session the client is bound to.
            client_id (str): Unique connection identifier.
            ws (WebSocketLike): Accepted WebSocket-like object.
        Returns:
            None: Side-effect only.
        Examples:
            >>> import asyncio
            >>> class _Echo:
            ...     async def send_text(self, data: str) -> None:
            ...         pass
            >>> t = WebChannelTransport()
            >>> asyncio.run(t.register(session_id="s", client_id="c", ws=_Echo()))
            >>> t.session_count("s")
            1
        """
        async with self._lock:
            bucket = self._by_session.setdefault(session_id, {})
            bucket[client_id] = ws
            self._by_client[client_id] = (session_id, ws)

    async def unregister(self, client_id: str) -> None:
        """Remove ``client_id`` from the registry (idempotent).
        Args:
            client_id (str): Identifier returned at register time.
        Returns:
            None: Side-effect only.
        Examples:
            >>> import asyncio
            >>> t = WebChannelTransport()
            >>> asyncio.run(t.unregister("missing"))
            >>> t.session_count("missing")
            0
        """
        async with self._lock:
            tup = self._by_client.pop(client_id, None)
            if tup is None:
                return
            session_id, _ws = tup
            bucket = self._by_session.get(session_id)
            if bucket is None:
                return
            bucket.pop(client_id, None)
            if not bucket:
                self._by_session.pop(session_id, None)

    def session_count(self, session_id: str) -> int:
        """Return the number of live connections subscribed to ``session_id``.
        Args:
            session_id (str): Lookup key.
        Returns:
            int: Connection count (``0`` when none).
        Examples:
            >>> WebChannelTransport().session_count("none")
            0
        """
        bucket = self._by_session.get(session_id)
        return len(bucket) if bucket else 0

    def session_for(self, client_id: str) -> str | None:
        """Return the ``session_id`` bound to ``client_id`` or ``None``.
        Args:
            client_id (str): Connection identifier.
        Returns:
            str | None: Session id when known.
        Examples:
            >>> WebChannelTransport().session_for("nope") is None
            True
        """
        tup = self._by_client.get(client_id)
        return tup[0] if tup else None

    async def send_to_session(self, session_id: str, frame_text: str) -> int:
        """Broadcast ``frame_text`` to every connection on ``session_id``.
        Connections that raise during ``send_text`` are unregistered so the
        registry never leaks dead clients (`specs/19-channel-webui.md` §3.2).
        Args:
            session_id (str): Target fan-out key.
            frame_text (str): Serialised JSON frame.
        Returns:
            int: Count of successful sends.
        Examples:
            >>> import asyncio
            >>> class _Boom:
            ...     async def send_text(self, data: str) -> None:
            ...         raise RuntimeError("dead")
            >>> t = WebChannelTransport()
            >>> asyncio.run(t.register(session_id="s", client_id="c", ws=_Boom()))
            >>> asyncio.run(t.send_to_session("s", "{}"))
            0
            >>> t.session_count("s")
            0
        """
        async with self._lock:
            bucket = dict(self._by_session.get(session_id, {}))
        if not bucket:
            return 0
        ok = 0
        dead: list[str] = []
        for client_id, ws in bucket.items():
            try:
                await ws.send_text(frame_text)
                ok += 1
            except Exception:
                logger.warning(
                    "webchat_send_failed session_id={} client_id={}",
                    session_id,
                    client_id,
                )
                dead.append(client_id)
        if dead:
            for client_id in dead:
                await self.unregister(client_id)
        return ok

    async def send_to_client(self, client_id: str, frame_text: str) -> bool:
        """Send a single frame to one connection (used for ``ready`` / errors).
        Args:
            client_id (str): Target client identifier.
            frame_text (str): Serialised JSON frame.
        Returns:
            bool: ``True`` when ``send_text`` succeeded, ``False`` otherwise.
        Examples:
            >>> import asyncio
            >>> t = WebChannelTransport()
            >>> asyncio.run(t.send_to_client("missing", "{}"))
            False
        """
        tup = self._by_client.get(client_id)
        if tup is None:
            return False
        _session_id, ws = tup
        try:
            await ws.send_text(frame_text)
            return True
        except Exception:
            logger.warning("webchat_send_failed client_id={}", client_id)
            await self.unregister(client_id)
            return False

    async def drain(self) -> None:
        """Clear all registrations (called by gateway shutdown).
        Returns:
            None: Side-effect only.
        Examples:
            >>> import asyncio
            >>> t = WebChannelTransport()
            >>> asyncio.run(t.drain())
        """
        async with self._lock:
            self._by_session.clear()
            self._by_client.clear()

    def __repr__(self) -> str:
        """Compact dev-friendly repr.
        Returns:
            str: ``WebChannelTransport(sessions=N, clients=M)``.
        Examples:
            >>> repr(WebChannelTransport()).startswith("WebChannelTransport")
            True
        """
        return (
            f"WebChannelTransport(sessions={len(self._by_session)}, clients={len(self._by_client)})"
        )


__all__ = ["WebChannelTransport", "WebSocketLike"]
