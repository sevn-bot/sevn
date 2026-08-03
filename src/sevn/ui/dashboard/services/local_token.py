"""File-based Mission Control local-open token (`specs/24-dashboard.md` §2.2).

Module: sevn.ui.dashboard.services.local_token
Depends: os, pathlib, secrets, sevn.config.loader, sevn.gateway.auth

Exports:
    dashboard_local_token_path — ``{SEVN_HOME}/dashboard-local-token``.
    write_dashboard_local_token — mint + persist boot token (mode 0600).
    read_dashboard_local_token — read persisted token text.
    dashboard_local_token_from_request — extract token from HTTP/WS handshake.
    verify_dashboard_local_token — timing-safe compare against boot token.
    direct_loopback_client — direct loopback client without forwarding headers.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from sevn.config.loader import operator_home_dir
from sevn.gateway.auth import secrets_compare

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request
    from starlette.websockets import WebSocket

DASHBOARD_LOCAL_TOKEN_HEADER = "X-Sevn-Dashboard-Local-Token"
DASHBOARD_LOCAL_TOKEN_QUERY = "local_token"
_DASHBOARD_LOCAL_TOKEN_FILENAME = "dashboard-local-token"


def dashboard_local_token_path(*, home: Path | None = None) -> Path:
    """Return the operator-local dashboard token file path.

    Args:
        home (Path | None): Override ``SEVN_HOME`` root (tests).

    Returns:
        Path: ``{operator_home}/dashboard-local-token``.

    Examples:
        >>> dashboard_local_token_path().name
        'dashboard-local-token'
    """
    root = home if home is not None else operator_home_dir()
    return root / _DASHBOARD_LOCAL_TOKEN_FILENAME


def write_dashboard_local_token(*, home: Path | None = None) -> str:
    """Mint and persist a dashboard local-open token (mode ``0600``).

    Args:
        home (Path | None): Override ``SEVN_HOME`` root (tests).

    Returns:
        str: Plaintext token written to disk.

    Examples:
        >>> from pathlib import Path
        >>> token = write_dashboard_local_token(home=Path('/tmp/sevn_w3_local_token_doctest'))
        >>> len(token) >= 32
        True
    """
    token = secrets.token_urlsafe(32)
    target = dashboard_local_token_path(home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{token}\n", encoding="utf-8")
    os.chmod(target, 0o600)
    return token


def read_dashboard_local_token(*, home: Path | None = None) -> str | None:
    """Read the persisted dashboard local-open token when present.

    Args:
        home (Path | None): Override ``SEVN_HOME`` root (tests).

    Returns:
        str | None: Token text or ``None`` when missing/unreadable.

    Examples:
        >>> read_dashboard_local_token(home=__import__('pathlib').Path('/nonexistent')) is None
        True
    """
    target = dashboard_local_token_path(home=home)
    try:
        raw = target.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw or None


def _forwarded_client_present(request: Request | WebSocket) -> bool:
    """Return whether reverse-proxy forwarding headers are present on the handshake.

    Never treat ``X-Forwarded-For`` / ``X-Real-IP`` as auth inputs — only as a signal
    that the TCP peer is not a direct loopback operator session.

    Args:
        request (Request | WebSocket): HTTP request or WebSocket connection.

    Returns:
        bool: ``True`` when a forwarding header is set.

    Examples:
        >>> _forwarded_client_present.__name__
        '_forwarded_client_present'
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return False
    return bool(
        headers.get("x-forwarded-for") or headers.get("x-real-ip") or headers.get("forwarded"),
    )


def dashboard_local_token_from_request(request: Request | WebSocket) -> str | None:
    """Extract a submitted dashboard local-open token from the handshake.

    Args:
        request (Request | WebSocket): HTTP request or WebSocket connection.

    Returns:
        str | None: Submitted token text when present.

    Examples:
        >>> dashboard_local_token_from_request.__name__
        'dashboard_local_token_from_request'
    """
    headers = getattr(request, "headers", None)
    if headers is not None:
        header_val = headers.get(DASHBOARD_LOCAL_TOKEN_HEADER)
        if isinstance(header_val, str) and header_val.strip():
            return header_val.strip()
    try:
        query_params = request.query_params
    except (AttributeError, KeyError):
        query_params = None
    if query_params is not None:
        query_val = query_params.get(DASHBOARD_LOCAL_TOKEN_QUERY)
        if isinstance(query_val, str) and query_val.strip():
            return query_val.strip()
    return None


def verify_dashboard_local_token(*, expected: str | None, submitted: str | None) -> bool:
    """Return whether ``submitted`` matches the boot-resolved local-open token.

    Args:
        expected (str | None): Token from ``app.state.dashboard_local_token``.
        submitted (str | None): Token from header/query.

    Returns:
        bool: ``True`` on match.

    Examples:
        >>> verify_dashboard_local_token(expected="abc", submitted="abc")
        True
        >>> verify_dashboard_local_token(expected="abc", submitted="bad")
        False
    """
    if not expected or not submitted:
        return False
    return secrets_compare(expected.strip(), submitted.strip())


def direct_loopback_client(request: Request | WebSocket) -> bool:
    """Return whether the client appears to be a direct loopback session.

    Reverse-proxied requests with forwarding headers are never treated as direct
    loopback even when ``client.host`` is ``127.0.0.1``.

    Args:
        request (Request | WebSocket): HTTP request or WebSocket connection.

    Returns:
        bool: ``True`` for direct loopback clients without forwarding headers.

    Examples:
        >>> direct_loopback_client.__name__
        'direct_loopback_client'
    """
    from sevn.ui.dashboard.services.auth import is_loopback_client_host

    if _forwarded_client_present(request):
        return False
    client = request.client
    return is_loopback_client_host(client.host if client is not None else None)


__all__ = [
    "DASHBOARD_LOCAL_TOKEN_HEADER",
    "DASHBOARD_LOCAL_TOKEN_QUERY",
    "dashboard_local_token_from_request",
    "dashboard_local_token_path",
    "direct_loopback_client",
    "read_dashboard_local_token",
    "verify_dashboard_local_token",
    "write_dashboard_local_token",
]
