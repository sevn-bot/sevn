"""Shared-secret guard for proxy ``POST /llm/*`` routes.

Module: sevn.proxy.auth
Depends: starlette

Exports:
    llm_post_auth_failure — return a JSON error response when blocked, else ``None``.
    proxy_allow_unauthenticated — whether ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` is set.
    log_proxy_allow_unauthenticated_boot_warning — loud boot warning for the opt-in path.

Examples:
    >>> from unittest.mock import MagicMock
    >>> from sevn.proxy.auth import llm_post_auth_failure
    >>> llm_post_auth_failure(MagicMock(method="GET"), None) is None
    True
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse

_PROXY_TOKEN_HEADER = "x-sevn-proxy-token"  # nosec B105
_GUARDED_PREFIXES = ("/llm/", "/web/", "/integration/")
PROXY_UNCONFIGURED_DETAIL = "proxy authentication not configured"


def proxy_allow_unauthenticated(*, env: Mapping[str, str] | None = None) -> bool:
    """Return whether unauthenticated guarded routes are explicitly permitted.

    Args:
        env (mapping | None): Env mapping; defaults to ``os.environ``.

    Returns:
        bool: ``True`` only when ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1``.

    Examples:
        >>> proxy_allow_unauthenticated(env={"SEVN_PROXY_ALLOW_UNAUTHENTICATED": "1"})
        True
        >>> proxy_allow_unauthenticated(env={})
        False
    """
    mapping = os.environ if env is None else env
    return str(mapping.get("SEVN_PROXY_ALLOW_UNAUTHENTICATED", "")).strip() == "1"


def log_proxy_allow_unauthenticated_boot_warning() -> None:
    """Log a loud warning when the unauthenticated opt-in is active at proxy boot.

    Returns:
        None: Logs only.

    Examples:
        >>> log_proxy_allow_unauthenticated_boot_warning.__name__
        'log_proxy_allow_unauthenticated_boot_warning'
    """
    if not proxy_allow_unauthenticated():
        return
    logger.warning(
        "SEVN_PROXY_ALLOW_UNAUTHENTICATED=1: egress proxy accepts unauthenticated "
        "requests on guarded routes (/llm/, /web/, /integration/)"
    )


def _is_guarded_path(path: str) -> bool:
    """Return whether ``path`` is covered by the shared-secret guard.

    Args:
        path (str): Request URL path.

    Returns:
        bool: ``True`` for guarded prefixes and exact ``/integration``.

    Examples:
        >>> _is_guarded_path("/llm/openai/chat/completions")
        True
        >>> _is_guarded_path("/integration")
        True
        >>> _is_guarded_path("/healthz")
        False
    """
    if path == "/integration":
        return True
    return any(path.startswith(prefix) for prefix in _GUARDED_PREFIXES)


def llm_post_auth_failure(request: Request, proxy_shared_secret: str | None) -> JSONResponse | None:
    """Enforce ``X-Sevn-Proxy-Token`` when a shared secret is configured.

    When ``proxy_shared_secret`` is unset or empty, guarded routes return **503**
    unless ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` (explicit dev-only opt-in).

    Args:
        request (Request): ASGI request (path + method + headers).
        proxy_shared_secret (str | None): Expected token; unset or empty fails closed.

    Returns:
        JSONResponse | None: ``503`` when auth is unconfigured; ``401`` when blocked;
        ``None`` when allowed.

    Examples:
        >>> from sevn.proxy.auth import llm_post_auth_failure
        >>> llm_post_auth_failure.__name__
        'llm_post_auth_failure'
    """
    path = getattr(getattr(request, "url", None), "path", None)
    if not isinstance(path, str) or not _is_guarded_path(path):
        return None
    if not proxy_shared_secret:
        if proxy_allow_unauthenticated():
            logger.warning(
                "proxy allow_unauthenticated opt-in: guarded request permitted without "
                "SEVN_PROXY_SHARED_SECRET (path={})",
                request.url.path,
            )
            return None
        return JSONResponse({"detail": PROXY_UNCONFIGURED_DETAIL}, status_code=503)
    token = request.headers.get(_PROXY_TOKEN_HEADER)
    if not hmac.compare_digest(token or "", proxy_shared_secret):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return None
