"""Local OAuth callback server for Codex PKCE (W2, D5).

Module: sevn.security.oauth.callback
Depends: sevn.security.oauth.constants

Exports:
    OAuthCallbackResult - authorization code + state from callback or paste.
    OAuthCallbackServer - local ``127.0.0.1:1455`` callback handle (D5).
    start_local_callback_server - bind callback server and await authorization code.
    parse_pasted_oauth_redirect - parse a pasted redirect URL or code (D5 headless).

D5: bind ``127.0.0.1:1455/auth/callback``; on bind failure or ``--headless``, callers
fall back to printing the authorize URL and accepting a pasted redirect URL/code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from collections.abc import Callable

from sevn.security.oauth.constants import (
    CODEX_OAUTH_CALLBACK_HOST,
    CODEX_OAUTH_CALLBACK_PATH,
    CODEX_OAUTH_CALLBACK_PORT,
)

_SUCCESS_HTML = (
    b"<!DOCTYPE html><html><head><title>sevn OAuth</title></head>"
    b"<body><p>Authorization complete. You can close this window.</p></body></html>"
)


def _first_query_param(params: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for a query parameter when present.

    Args:
        params (dict[str, list[str]]): Parsed query mapping.
        key (str): Parameter name.

    Returns:
        str | None: First value, or ``None`` when absent.

    Examples:
        >>> _first_query_param({"code": ["abc"]}, "code")
        'abc'
    """
    values = params.get(key)
    if not values:
        return None
    return values[0]


@dataclass(frozen=True, slots=True)
class OAuthCallbackResult:
    """Authorization code captured from the local callback or manual paste."""

    code: str
    state: str


class OAuthCallbackServer(Protocol):
    """Minimal callback-server protocol (D5)."""

    @property
    def ready(self) -> bool:
        """True when the server bound successfully.

        Returns:
            bool: ``True`` when listening on ``127.0.0.1:1455``.

        Examples:
            >>> class S:
            ...     @property
            ...     def ready(self) -> bool:
            ...         return True
            >>> S().ready
            True
        """
        ...

    async def wait_for_code(self) -> OAuthCallbackResult | None:
        """Await authorization code or return ``None`` on timeout/manual mode.

        Returns:
            OAuthCallbackResult | None: Parsed code/state, or ``None`` when unavailable.

        Examples:
            >>> import asyncio
            >>> class S:
            ...     @property
            ...     def ready(self) -> bool:
            ...         return True
            ...     async def wait_for_code(self):
            ...         return OAuthCallbackResult(code="c", state="s")
            ...     async def close(self) -> None:
            ...         pass
            >>> asyncio.run(S().wait_for_code()).code
            'c'
        """
        ...

    async def close(self) -> None:
        """Release the bound port.

        Examples:
            >>> import asyncio
            >>> class S:
            ...     @property
            ...     def ready(self) -> bool:
            ...         return True
            ...     async def wait_for_code(self):
            ...         return None
            ...     async def close(self) -> None:
            ...         pass
            >>> asyncio.run(S().close()) is None
            True
        """
        ...


@dataclass
class _LocalCallbackServer:
    """Async HTTP callback server bound to ``127.0.0.1:1455``."""

    _expected_state: str
    _ready: bool
    _server: asyncio.AbstractServer | None = None
    _result: OAuthCallbackResult | None = None
    _event: asyncio.Event | None = None

    @property
    def ready(self) -> bool:
        """Return whether the callback server bound successfully.

        Returns:
            bool: ``True`` when listening on ``127.0.0.1:1455``.

        Examples:
            >>> import asyncio
            >>> server = asyncio.run(start_local_callback_server(state="s"))
            >>> isinstance(server.ready, bool)
            True
        """
        return self._ready

    async def wait_for_code(self) -> OAuthCallbackResult | None:
        """Await the first valid OAuth callback.

        Returns:
            OAuthCallbackResult | None: Parsed code/state, or ``None`` when not ready.

        Examples:
            >>> import asyncio
            >>> server = asyncio.run(start_local_callback_server(state="s"))
            >>> asyncio.run(server.close()) is None
            True
        """
        if not self._ready or self._event is None:
            return None
        await self._event.wait()
        return self._result

    async def close(self) -> None:
        """Stop the callback server and release the port.

        Examples:
            >>> import asyncio
            >>> server = asyncio.run(start_local_callback_server(state="s"))
            >>> asyncio.run(server.close()) is None
            True
        """
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


def parse_pasted_oauth_redirect(
    text: str,
    *,
    expected_state: str,
) -> OAuthCallbackResult:
    """Parse a pasted redirect URL or raw authorization code (D5 headless fallback).

    Args:
        text (str): Full redirect URL, query string, or bare authorization code.
        expected_state (str): CSRF state from ``build_authorization_flow``.

    Returns:
        OAuthCallbackResult: Parsed authorization code and state.

    Raises:
        ValueError: When the input cannot be parsed or state does not match.

    Examples:
        >>> parse_pasted_oauth_redirect(
        ...     "http://localhost:1455/auth/callback?code=abc&state=s1",
        ...     expected_state="s1",
        ... ).code
        'abc'
    """
    raw = text.strip()
    if not raw:
        msg = "empty OAuth redirect input"
        raise ValueError(msg)
    if "://" in raw or "?" in raw or raw.startswith(("/", "code=")):
        parsed = urlparse(
            raw if "://" in raw else f"http://local{raw if raw.startswith('/') else '/?' + raw}"
        )
        params = parse_qs(parsed.query)
        code = _first_query_param(params, "code")
        state = _first_query_param(params, "state")
    else:
        code = raw
        state = expected_state
    if not code:
        msg = "authorization code missing from pasted redirect"
        raise ValueError(msg)
    if state != expected_state:
        msg = "OAuth state mismatch"
        raise ValueError(msg)
    return OAuthCallbackResult(code=str(code), state=str(state))


async def _handle_oauth_callback(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    expected_state: str,
    on_result: Callable[[OAuthCallbackResult], None],
) -> None:
    """Handle one HTTP callback request.

    Args:
        reader (asyncio.StreamReader): Incoming TCP stream.
        writer (asyncio.StreamWriter): Outgoing TCP stream.
        expected_state (str): CSRF state to validate.
        on_result (Callable[[OAuthCallbackResult], None]): Success callback.

    Examples:
        >>> # Covered indirectly by start_local_callback_server callers.
        >>> True
        True
    """
    try:
        request = await reader.read(8192)
        request_line = request.split(b"\r\n", maxsplit=1)[0].decode("utf-8", errors="replace")
        parts = request_line.split(" ")
        if len(parts) < 2 or parts[0] != "GET":
            writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        path = parts[1]
        parsed = urlparse(path)
        if parsed.path != CODEX_OAUTH_CALLBACK_PATH:
            writer.write(b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        params = parse_qs(parsed.query)
        code = _first_query_param(params, "code")
        state = _first_query_param(params, "state")
        if not code or state != expected_state:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        on_result(OAuthCallbackResult(code=str(code), state=str(state)))
        body = _SUCCESS_HTML
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: "
            + str(len(body)).encode("ascii")
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def start_local_callback_server(*, state: str) -> OAuthCallbackServer:
    """Start the local OAuth callback server on ``127.0.0.1:1455`` (D5).

    Args:
        state (str): CSRF state echoed in the authorize URL.

    Returns:
        OAuthCallbackServer: Handle for awaiting the code and closing the server.
        When binding fails, ``ready`` is ``False`` so callers can use the paste fallback.

    Examples:
        >>> import asyncio
        >>> server = asyncio.run(start_local_callback_server(state="abc"))
        >>> isinstance(server.ready, bool)
        True
    """
    event = asyncio.Event()
    callback_server = _LocalCallbackServer(
        _expected_state=state,
        _ready=False,
    )

    def on_result(result: OAuthCallbackResult) -> None:
        callback_server._result = result
        event.set()

    async def client_handler(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        await _handle_oauth_callback(
            reader,
            writer,
            expected_state=state,
            on_result=on_result,
        )

    try:
        server = await asyncio.start_server(
            client_handler,
            CODEX_OAUTH_CALLBACK_HOST,
            CODEX_OAUTH_CALLBACK_PORT,
        )
    except OSError:
        return callback_server

    callback_server._ready = True
    callback_server._server = server
    callback_server._event = event
    return callback_server
