"""Shared egress proxy ``/integration`` POST helper for skill libraries.

Module: sevn.integrations.proxy_client
Depends: httpx, os, sevn.config.settings, sevn.tools.web

Exports:
    integration_post_async — async POST to proxy ``/integration``.
    integration_post_sync — synchronous POST to proxy ``/integration``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from sevn.config.settings import ProcessSettings
from sevn.tools.web import build_egress_web_headers, proxy_post_json

_PROXY_INTEGRATION_PATH = "/integration"


def _resolve_process_egress() -> tuple[str | None, str | None, str | None]:
    """Read proxy URL, session token, and shared secret from process env.

    Returns:
        tuple[str | None, str | None, str | None]: Egress triple.

    Examples:
        >>> isinstance(_resolve_process_egress(), tuple)
        True
    """
    ps = ProcessSettings()
    proxy_url = (ps.proxy_url or "").strip() or None
    session_token = (ps.session_token or "").strip() or None
    shared_secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip() or None
    return proxy_url, session_token, shared_secret


async def integration_post_async(
    *,
    service: str,
    method: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """POST one integration dispatch to the egress proxy.

    Args:
        service (str): Integration namespace (``cursor``, ``github``, ...).
        method (str): Method name within the service.
        args (dict[str, Any]): JSON-safe arguments.

    Returns:
        dict[str, Any]: Parsed proxy response body.

    Raises:
        RuntimeError: When proxy is unset or returns an error status.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(integration_post_async)
        True
    """
    proxy_url, session_token, shared_secret = _resolve_process_egress()
    if not proxy_url:
        msg = "SEVN_PROXY_URL is not configured"
        raise RuntimeError(msg)
    body = {"service": service, "method": method, "args": dict(args)}
    headers = build_egress_web_headers(
        proxy_url=proxy_url,
        session_token=session_token,
        proxy_shared_secret=shared_secret,
    )
    status, data = await proxy_post_json(
        proxy_url=proxy_url,
        path=_PROXY_INTEGRATION_PATH,
        body=body,
        headers=headers,
    )
    if status >= 400:
        detail = str(data.get("detail") or data.get("error") or f"proxy status {status}")
        raise RuntimeError(detail)
    return data


def integration_post_sync(
    *,
    service: str,
    method: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous wrapper for :func:`integration_post_async`.

    Args:
        service (str): Integration namespace.
        method (str): Method name.
        args (dict[str, Any]): Arguments payload.

    Returns:
        dict[str, Any]: Parsed response.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(integration_post_sync)
        True
    """
    return asyncio.run(integration_post_async(service=service, method=method, args=args))
