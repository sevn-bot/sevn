"""Reverse-proxy noVNC behind the gateway when ``SEVN_NOVNC_UPSTREAM`` is set.

HTTP assets and the viewer HTML are served under ``/gui``; WebSocket VNC traffic
is proxied at ``/gui/websockify``. Browsers authenticate via ``?token=`` (or a
session cookie minted from it); API clients may use ``Authorization: Bearer``.
Port 6080 stays container-internal.

Module: sevn.gateway.gui_proxy
Depends: asyncio, os, httpx, starlette

Exports:
    mount_gui_proxy — register ``/gui`` HTTP + WebSocket proxy routes on the app.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

import httpx
from fastapi import Depends, HTTPException, Request, WebSocket
from starlette.responses import RedirectResponse, Response

if TYPE_CHECKING:
    from fastapi import FastAPI

GUI_SESSION_COOKIE = "sevn_gui_session"
_NOVNC_WS_PATH = "gui/websockify"


def _novnc_upstream() -> str | None:
    """Return trimmed ``SEVN_NOVNC_UPSTREAM`` base URL when set.

    Returns:
        str | None: Upstream base URL without trailing slash.

    Examples:
        >>> _novnc_upstream() is None or _novnc_upstream().startswith("http")
        True
    """
    raw = (os.environ.get("SEVN_NOVNC_UPSTREAM") or "").strip().rstrip("/")
    return raw or None


def _upstream_ws_url(upstream: str, path: str, *, query: str = "") -> str:
    """Build a WebSocket URL for the internal noVNC websockify endpoint.

    Args:
        upstream (str): HTTP(S) ``SEVN_NOVNC_UPSTREAM`` base URL.
        path (str): Path segment after the upstream host (e.g. ``websockify``).
        query (str): Optional query string without leading ``?``.

    Returns:
        str: ``ws://`` or ``wss://`` URL for websockets.connect.

    Examples:
        >>> _upstream_ws_url("http://127.0.0.1:6080", "websockify")
        'ws://127.0.0.1:6080/websockify'
    """
    if upstream.startswith("https://"):
        base = "wss://" + upstream.removeprefix("https://")
    elif upstream.startswith("http://"):
        base = "ws://" + upstream.removeprefix("http://")
    else:
        base = upstream
    url = f"{base}/{path.lstrip('/')}"
    if query:
        return f"{url}?{query}"
    return url


def _gui_gateway_credentials(
    *,
    authorization_header: str | None,
    query_params: Mapping[str, str],
    cookies: Mapping[str, str],
) -> list[str]:
    """Return all submitted gateway tokens from header, query, and session cookie.

    Args:
        authorization_header (str | None): Raw ``Authorization`` header.
        query_params (Mapping[str, str]): Request query parameters.
        cookies (Mapping[str, str]): Request cookies.

    Returns:
        list[str]: Distinct submitted token values, header first then query then cookie.

    Examples:
        >>> _gui_gateway_credentials(
        ...     authorization_header="Bearer abc",
        ...     query_params={"token": "def"},
        ...     cookies={"sevn_gui_session": "ghi"},
        ... )
        ['abc', 'def', 'ghi']
    """
    from sevn.gateway.auth import extract_bearer

    credentials: list[str] = []
    bearer = extract_bearer(authorization_header)
    if bearer:
        credentials.append(bearer)
    token_q = (query_params.get("token") or "").strip()
    if token_q:
        credentials.append(token_q)
    cookie = (cookies.get(GUI_SESSION_COOKIE) or "").strip()
    if cookie:
        credentials.append(cookie)
    return credentials


def _verify_gui_gateway_access(
    *,
    configured: str | None,
    authorization_header: str | None,
    query_params: Mapping[str, str],
    cookies: Mapping[str, str],
) -> bool:
    """Return ``True`` when the client may access GUI proxy routes.

    Args:
        configured (str | None): Boot-time gateway bearer token.
        authorization_header (str | None): Raw ``Authorization`` header.
        query_params (Mapping[str, str]): Request query parameters.
        cookies (Mapping[str, str]): Request cookies.

    Returns:
        bool: Access decision.

    Examples:
        >>> _verify_gui_gateway_access(
        ...     configured="secret-token-at-least-32-characters-long",
        ...     authorization_header=None,
        ...     query_params={"token": "wrong-token-at-least-32-characters-long"},
        ...     cookies={"sevn_gui_session": "secret-token-at-least-32-characters-long"},
        ... )
        True
    """
    from sevn.gateway.auth import secrets_compare

    if not configured:
        return True
    expected = configured.strip()
    credentials = _gui_gateway_credentials(
        authorization_header=authorization_header,
        query_params=query_params,
        cookies=cookies,
    )
    if not credentials:
        return False
    return any(secrets_compare(expected, submitted.strip()) for submitted in credentials)


def _fresh_gui_gateway_credential(
    *,
    authorization_header: str | None,
    query_params: Mapping[str, str],
) -> str | None:
    """Return a gateway token supplied explicitly via header or query (not cookie).

    Args:
        authorization_header (str | None): Raw ``Authorization`` header.
        query_params (Mapping[str, str]): Request query parameters.

    Returns:
        str | None: Fresh token text when present.

    Examples:
        >>> _fresh_gui_gateway_credential(
        ...     authorization_header="Bearer abc",
        ...     query_params={},
        ... )
        'abc'
    """
    from sevn.gateway.auth import extract_bearer

    bearer = extract_bearer(authorization_header)
    if bearer:
        return bearer
    token_q = (query_params.get("token") or "").strip()
    return token_q or None


def _maybe_set_gui_session_cookie(
    response: Response,
    *,
    configured: str | None,
    authorization_header: str | None,
    query_params: Mapping[str, str],
    cookies: Mapping[str, str],
) -> None:
    """Persist or renew the GUI session cookie after query/header authentication.

    Args:
        response (Response): Outbound response (redirect or proxied body wrapper).
        configured (str | None): Boot-time gateway bearer token.
        authorization_header (str | None): Raw ``Authorization`` header.
        query_params (Mapping[str, str]): Request query parameters.
        cookies (Mapping[str, str]): Request cookies.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_maybe_set_gui_session_cookie)
        True
    """
    from sevn.gateway.auth import secrets_compare

    if not configured:
        return
    fresh = _fresh_gui_gateway_credential(
        authorization_header=authorization_header,
        query_params=query_params,
    )
    if not fresh or not secrets_compare(configured.strip(), fresh.strip()):
        return
    existing = (cookies.get(GUI_SESSION_COOKIE) or "").strip()
    if existing and secrets_compare(existing, fresh):
        return
    response.set_cookie(
        GUI_SESSION_COOKIE,
        value=fresh,
        httponly=True,
        samesite="lax",
        path="/gui",
    )


async def _authorize_gui_ws(
    websocket: WebSocket,
    resolve_gateway_token: Callable[[Request], str | None],
) -> bool:
    """Validate the WebSocket handshake using gateway bearer, query, or cookie.

    Args:
        websocket (WebSocket): Incoming client WebSocket.
        resolve_gateway_token (Callable[[Request], str | None]): Boot-time token resolver.

    Returns:
        bool: ``True`` when the client is authorized.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_authorize_gui_ws)
        True
    """
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/gui/websockify",
        "headers": websocket.scope.get("headers", []),
        "query_string": websocket.scope.get("query_string", b""),
        "app": websocket.app,
    }
    request = Request(scope)
    configured = resolve_gateway_token(request)
    return _verify_gui_gateway_access(
        configured=configured,
        authorization_header=websocket.headers.get("authorization"),
        query_params=websocket.query_params,
        cookies=websocket.cookies,
    )


async def _relay_gui_websocket(websocket: WebSocket, backend_url: str) -> None:
    """Bidirectionally relay frames between the client and internal websockify.

    Args:
        websocket (WebSocket): Accepted client WebSocket.
        backend_url (str): Internal ``ws://`` websockify URL.

    Returns:
        None

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_relay_gui_websocket)
        True
    """
    import websockets

    async with websockets.connect(backend_url) as backend:

        async def client_to_backend() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                payload = message.get("bytes")
                if payload is not None:
                    await backend.send(payload)
                    continue
                text = message.get("text")
                if text is not None:
                    await backend.send(text)

        async def backend_to_client() -> None:
            async for payload in backend:
                if isinstance(payload, bytes):
                    await websocket.send_bytes(payload)
                else:
                    await websocket.send_text(str(payload))

        client_task = asyncio.create_task(client_to_backend())
        backend_task = asyncio.create_task(backend_to_client())
        _done, pending = await asyncio.wait(
            {client_task, backend_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def mount_gui_proxy(
    app: FastAPI,
    *,
    resolve_gateway_token: Callable[[Request], str | None],
) -> None:
    """Mount noVNC HTTP + WebSocket reverse proxy at ``/gui`` when configured.

    Args:
        app (FastAPI): Gateway application.
        resolve_gateway_token (Callable[[Request], str | None]): Boot-time token resolver.

    Returns:
        None

    Examples:
        >>> from fastapi import FastAPI as _FastAPI
        >>> mount_gui_proxy(_FastAPI(), resolve_gateway_token=lambda _r: None) is None
        True
    """
    upstream = _novnc_upstream()
    if not upstream:
        return

    async def enforce_gui_auth(request: Request) -> None:
        configured = resolve_gateway_token(request)
        if _verify_gui_gateway_access(
            configured=configured,
            authorization_header=request.headers.get("Authorization"),
            query_params=request.query_params,
            cookies=request.cookies,
        ):
            return
        raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/gui", include_in_schema=False)
    async def gui_root(request: Request, _ok: None = Depends(enforce_gui_auth)) -> RedirectResponse:
        """Redirect ``/gui`` to the noVNC viewer."""
        configured = resolve_gateway_token(request)
        response = RedirectResponse(
            url=f"/gui/vnc.html?autoconnect=1&resize=scale&path={_NOVNC_WS_PATH}",
            status_code=307,
        )
        _maybe_set_gui_session_cookie(
            response,
            configured=configured,
            authorization_header=request.headers.get("Authorization"),
            query_params=request.query_params,
            cookies=request.cookies,
        )
        return response

    @app.api_route(
        "/gui/{full_path:path}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def gui_http_proxy(
        full_path: str,
        request: Request,
        _ok: None = Depends(enforce_gui_auth),
    ) -> Response:
        """Proxy noVNC static assets from the internal websockify port."""
        target = f"{upstream}/{full_path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            proxied = await client.request(
                request.method,
                target,
                headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            )
        headers = {
            k: v
            for k, v in proxied.headers.items()
            if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}
        }
        response = Response(
            content=proxied.content, status_code=proxied.status_code, headers=headers
        )
        _maybe_set_gui_session_cookie(
            response,
            configured=resolve_gateway_token(request),
            authorization_header=request.headers.get("Authorization"),
            query_params=request.query_params,
            cookies=request.cookies,
        )
        return response

    @app.websocket("/gui/websockify")
    async def gui_ws_proxy(websocket: WebSocket) -> None:
        """Proxy noVNC WebSocket traffic to internal websockify (authenticated)."""
        if not await _authorize_gui_ws(websocket, resolve_gateway_token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        backend_url = _upstream_ws_url(upstream, "websockify", query=websocket.url.query)
        await _relay_gui_websocket(websocket, backend_url)


__all__ = ["GUI_SESSION_COOKIE", "mount_gui_proxy"]
