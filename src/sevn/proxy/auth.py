"""Shared-secret guard for proxy ``POST /llm/*`` routes.

Module: sevn.proxy.auth
Depends: starlette

Exports:
    llm_post_auth_failure — return a JSON error response when blocked, else ``None``.

Examples:
    >>> from unittest.mock import MagicMock
    >>> from sevn.proxy.auth import llm_post_auth_failure
    >>> llm_post_auth_failure(MagicMock(method="GET"), None) is None
    True
"""

from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.responses import JSONResponse

_PROXY_TOKEN_HEADER = "x-sevn-proxy-token"  # nosec B105


def llm_post_auth_failure(request: Request, proxy_shared_secret: str | None) -> JSONResponse | None:
    """Enforce ``X-Sevn-Proxy-Token`` when a shared secret is configured.

        Args:
    request (Request): ASGI request (path + method + headers).
    proxy_shared_secret (str | None): Expected token; unset or empty skips the guard.

        Returns:
            JSONResponse | None: ``401`` when blocked; ``None`` when allowed.

        Examples:
            >>> from sevn.proxy.auth import llm_post_auth_failure
            >>> llm_post_auth_failure.__name__
            'llm_post_auth_failure'
    """
    if not proxy_shared_secret:
        return None
    if request.method != "POST":
        return None
    guarded_prefixes = ("/llm/", "/web/", "/integration/")
    if not any(request.url.path.startswith(prefix) for prefix in guarded_prefixes):
        return None
    token = request.headers.get(_PROXY_TOKEN_HEADER)
    if not hmac.compare_digest(token or "", proxy_shared_secret):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return None
