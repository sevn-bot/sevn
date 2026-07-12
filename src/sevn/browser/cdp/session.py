"""Session-bound CDP view: route commands/events to one attached target.

A :class:`CDPSession` wraps a :class:`CDPConnection` plus a ``sessionId`` so callers
write ``await session.send("Page.navigate", {...})`` without threading the session id
through every call. The browser-level session has ``session_id is None``.

Module: sevn.browser.cdp.session
Depends: sevn.browser.cdp.connection

Exports:
    CDPSession — send/wait_for/on bound to one target session.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(CDPSession.send)
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sevn.browser.cdp.connection import CDPConnection, EventCallback

_DEFAULT_TIMEOUT: Final[float] = 30.0


class CDPSession:
    """A ``sessionId``-bound view over a shared :class:`CDPConnection`."""

    def __init__(
        self,
        connection: CDPConnection,
        session_id: str | None = None,
        *,
        target_id: str | None = None,
    ) -> None:
        """Bind a connection and (optional) target session id.

        Args:
            connection (CDPConnection): Shared browser-level connection.
            session_id (str | None): Flattened target session id; ``None`` ⇒ browser-level.
            target_id (str | None): CDP ``targetId`` this session attaches to, when known.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPSession.__init__)
            True
        """
        self._conn = connection
        self._session_id = session_id
        self._target_id = target_id
        self._enabled: set[str] = set()

    @property
    def connection(self) -> CDPConnection:
        """Return the underlying shared connection.

        Returns:
            CDPConnection: The browser-level connection.

        Examples:
            >>> import inspect
            >>> isinstance(CDPSession.connection, property)
            True
        """
        return self._conn

    @property
    def session_id(self) -> str | None:
        """Return the bound target session id (``None`` for browser-level).

        Returns:
            str | None: Flattened ``sessionId`` or ``None``.

        Examples:
            >>> import inspect
            >>> isinstance(CDPSession.session_id, property)
            True
        """
        return self._session_id

    @property
    def target_id(self) -> str | None:
        """Return the CDP ``targetId`` this session attaches to, when known.

        Returns:
            str | None: Target id string or ``None``.

        Examples:
            >>> import inspect
            >>> isinstance(CDPSession.target_id, property)
            True
        """
        return self._target_id

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a CDP command on this session and return its ``result``.

        Args:
            method (str): CDP method.
            params (dict[str, Any] | None): Method params.
            timeout (float): Seconds to await the reply.

        Returns:
            dict[str, Any]: The command ``result``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPSession.send)
            True
        """
        return await self._conn.send(method, params, session_id=self._session_id, timeout=timeout)

    async def enable(self, domain: str, params: dict[str, Any] | None = None) -> None:
        """Enable a CDP ``<Domain>.enable`` once per session (idempotent).

        Args:
            domain (str): Domain name, for example ``Page`` or ``DOM``.
            params (dict[str, Any] | None): Optional enable params.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPSession.enable)
            True
        """
        if domain in self._enabled:
            return
        await self.send(f"{domain}.enable", params)
        self._enabled.add(domain)

    async def wait_for(
        self,
        method: str,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Wait for the next ``method`` event on this session.

        Args:
            method (str): CDP event method.
            predicate (Callable[[dict[str, Any]], bool] | None): Extra filter on the message.
            timeout (float): Seconds before raising :class:`TimeoutError`.

        Returns:
            dict[str, Any]: The matching raw event message.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(CDPSession.wait_for)
            True
        """
        return await self._conn.wait_for(
            method, predicate=predicate, timeout=timeout, session_id=self._session_id
        )

    def on(self, method: str, callback: EventCallback) -> Callable[[], None]:
        """Register a listener for events of ``method`` on this session only.

        Args:
            method (str): CDP event method.
            callback (EventCallback): Sync or async callable receiving the raw message.

        Returns:
            Callable[[], None]: A disposer that removes the listener.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(CDPSession.on)
            True
        """
        sid = self._session_id

        def _scoped(message: dict[str, Any]) -> None | Awaitable[None]:
            if sid is not None and message.get("sessionId") != sid:
                return None
            return callback(message)

        return self._conn.on(method, _scoped)


__all__ = ["CDPSession"]
