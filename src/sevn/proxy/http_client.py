"""Shared ``httpx.AsyncClient`` factory for the egress proxy lifespan.

Module: sevn.proxy.http_client
Depends: httpx, sevn.config.defaults

Exports:
    build_proxy_upstream_timeout — granular upstream ``httpx.Timeout``.
    create_proxy_http_client — lifespan ``AsyncClient`` for ``create_app``.

Examples:
    >>> from sevn.proxy.http_client import PROXY_HTTP_LIMITS
    >>> PROXY_HTTP_LIMITS.max_connections
    20
"""

from __future__ import annotations

import httpx

from sevn.config.defaults import (
    PROXY_HTTP_MAX_CONNECTIONS,
    PROXY_HTTP_MAX_KEEPALIVE_CONNECTIONS,
    PROXY_UPSTREAM_TIMEOUT_CONNECT_S,
    PROXY_UPSTREAM_TIMEOUT_POOL_S,
    PROXY_UPSTREAM_TIMEOUT_READ_S,
    PROXY_UPSTREAM_TIMEOUT_WRITE_S,
)

PROXY_HTTP_LIMITS: httpx.Limits = httpx.Limits(
    max_connections=PROXY_HTTP_MAX_CONNECTIONS,
    max_keepalive_connections=PROXY_HTTP_MAX_KEEPALIVE_CONNECTIONS,
)


def build_proxy_upstream_timeout(*, max_html_chars: int | None = None) -> httpx.Timeout:
    """Build upstream fetch timeout with optional read scaling for large pages.

    Args:
        max_html_chars (int | None): Character cap for the response body; when set,
            read budget scales as ``min(90, 30 + max_html_chars // 50_000)``.

    Returns:
        httpx.Timeout: Connect/read/write/pool timeouts for upstream GET/stream.

    Examples:
        >>> t = build_proxy_upstream_timeout()
        >>> t.connect
        10.0
        >>> build_proxy_upstream_timeout(max_html_chars=1_000_000).read
        50.0
    """
    read_s = float(PROXY_UPSTREAM_TIMEOUT_READ_S)
    if max_html_chars is not None:
        read_s = min(read_s, 30.0 + max_html_chars // 50_000)
    return httpx.Timeout(
        connect=PROXY_UPSTREAM_TIMEOUT_CONNECT_S,
        read=read_s,
        write=PROXY_UPSTREAM_TIMEOUT_WRITE_S,
        pool=PROXY_UPSTREAM_TIMEOUT_POOL_S,
    )


def create_proxy_http_client() -> httpx.AsyncClient:
    """Create the process-scoped upstream ``httpx.AsyncClient`` for the proxy.

    Returns:
        httpx.AsyncClient: Caller must ``aclose()`` on shutdown (lifespan hook).

    Examples:
        >>> client = create_proxy_http_client()
        >>> client.timeout.connect
        10.0
    """
    return httpx.AsyncClient(
        timeout=build_proxy_upstream_timeout(),
        limits=PROXY_HTTP_LIMITS,
        follow_redirects=True,
    )


__all__ = [
    "PROXY_HTTP_LIMITS",
    "build_proxy_upstream_timeout",
    "create_proxy_http_client",
]
