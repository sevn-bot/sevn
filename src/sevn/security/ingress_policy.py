"""Central HTTP/WebSocket ingress limits (`specs/17-gateway.md`, issue #81).

Module: sevn.security.ingress_policy
Depends: starlette, sevn.config.defaults

Exports:
    IngressBodyLimitMiddleware — ASGI middleware rejecting oversized HTTP bodies.
    ingress_body_too_large_response — shared 413 response factory.
    read_limited_body — bounded ``request.body()`` helper.
    first_ws_frame_within_limit — webchat auth-frame size guard.
    wire_ingress_body_limit — register body-cap middleware on a gateway app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI

from starlette.requests import Request  # noqa: TC002
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send  # noqa: TC002

from sevn.config.defaults import DEFAULT_MAX_INGRESS_BODY_BYTES

_INGRESS_CAP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def ingress_body_too_large_response() -> Response:
    """Return the canonical 413 response for oversize ingress bodies.

    Returns:
        Response: Empty body with status 413.

    Examples:
        >>> ingress_body_too_large_response().status_code
        413
    """
    return Response(status_code=413, content=b"")


def _content_length_exceeds_cap(headers: Mapping[str, str], *, max_bytes: int) -> bool:
    """Return ``True`` when ``Content-Length`` exceeds ``max_bytes``.

    Args:
        headers (MutableMapping[str, str]): Request headers (lower-cased keys).
        max_bytes (int): Maximum allowed body size in bytes.

    Returns:
        bool: ``True`` when the declared body is too large.

    Examples:
        >>> _content_length_exceeds_cap({"content-length": "10"}, max_bytes=5)
        True
    """
    raw = headers.get("content-length")
    if not raw:
        return False
    try:
        return int(raw) > max_bytes
    except ValueError:
        return False


class IngressBodyLimitMiddleware:
    """Reject HTTP bodies above ``max_bytes`` before route handlers run."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = DEFAULT_MAX_INGRESS_BODY_BYTES) -> None:
        """Wrap ``app`` with a hard body-size cap for mutating HTTP methods.

        Args:
            app (ASGIApp): Inner ASGI application.
            max_bytes (int): Maximum allowed request body size in bytes.

        Returns:
            None: Always ``None``.

        Examples:
            >>> IngressBodyLimitMiddleware(object(), max_bytes=1024).max_bytes
            1024
        """
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entrypoint enforcing the configured ingress body cap.

        Args:
            scope (Scope): ASGI connection scope.
            receive (Receive): Upstream receive callable.
            send (Send): Downstream send callable.

        Returns:
            None: Always ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(IngressBodyLimitMiddleware.__call__)
            True
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "").upper()
        if method not in _INGRESS_CAP_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        if _content_length_exceeds_cap(headers, max_bytes=self.max_bytes):
            response = ingress_body_too_large_response()
            await response(scope, receive, send)
            return

        received = 0
        rejected = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] != "http.request":
                return message
            chunk = message.get("body", b"") or b""
            received += len(chunk)
            if received > self.max_bytes:
                rejected = True
                return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            nonlocal response_started
            if rejected:
                if message["type"] == "http.response.start" and not response_started:
                    response_started = True
                    response = ingress_body_too_large_response()
                    await response(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, limited_send)
        if rejected and not response_started:
            response = ingress_body_too_large_response()
            await response(scope, receive, send)


async def read_limited_body(
    request: Request,
    *,
    max_bytes: int = DEFAULT_MAX_INGRESS_BODY_BYTES,
) -> bytes:
    """Read the request body, raising ``HTTPException(413)`` when over ``max_bytes``.

    Args:
        request (Request): Active Starlette request.
        max_bytes (int): Maximum allowed raw body size.

    Returns:
        bytes: Full request body within the cap.

    Raises:
        HTTPException: When ``Content-Length`` or streamed body exceeds ``max_bytes``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(read_limited_body)
        True
    """
    from fastapi import HTTPException

    if _content_length_exceeds_cap(dict(request.headers), max_bytes=max_bytes):
        raise HTTPException(status_code=413)
    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(status_code=413)
    return body


def first_ws_frame_within_limit(frame: Mapping[str, Any], *, max_bytes: int) -> bool:
    """Return ``False`` when a websocket frame exceeds ``max_bytes``.

    Args:
        frame (dict[str, Any]): Frame dict from ``WebSocket.receive*``.
        max_bytes (int): Maximum allowed payload size.

    Returns:
        bool: ``True`` when within limit or not a payload frame.

    Examples:
        >>> first_ws_frame_within_limit({"type": "websocket.receive", "bytes": b"x"}, max_bytes=10)
        True
        >>> first_ws_frame_within_limit({"type": "websocket.receive", "bytes": b"x" * 11}, max_bytes=10)
        False
    """
    if frame.get("type") != "websocket.receive":
        return True
    payload = frame.get("bytes")
    if isinstance(payload, (bytes, bytearray)):
        return len(payload) <= max_bytes
    text = frame.get("text")
    if isinstance(text, str):
        return len(text.encode("utf-8")) <= max_bytes
    return True


def wire_ingress_body_limit(
    app: FastAPI,
    *,
    max_bytes: int = DEFAULT_MAX_INGRESS_BODY_BYTES,
) -> None:
    """Register ingress body-size middleware on a gateway FastAPI app.

    Args:
        app (FastAPI): Gateway application instance.
        max_bytes (int): Maximum allowed request body size in bytes.

    Returns:
        None: Side-effect only.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(wire_ingress_body_limit)
        True
    """
    app.add_middleware(
        IngressBodyLimitMiddleware,
        max_bytes=max_bytes,
    )


__all__ = [
    "IngressBodyLimitMiddleware",
    "first_ws_frame_within_limit",
    "ingress_body_too_large_response",
    "read_limited_body",
    "wire_ingress_body_limit",
]
