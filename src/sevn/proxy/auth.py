"""Shared-secret and scoped session-token guard for proxy guarded routes.

Module: sevn.proxy.auth
Depends: starlette

Exports:
    llm_post_auth_failure — return a JSON error response when blocked, else ``None``.
    mint_session_token — mint a scoped per-run ``X-Sevn-Session-Token``.
    validate_session_token — verify signature, expiry, and route-family scope.
    proxy_allow_unauthenticated — whether ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` is set.
    log_proxy_allow_unauthenticated_boot_warning — loud boot warning for the opt-in path.

Examples:
    >>> from unittest.mock import MagicMock
    >>> from sevn.proxy.auth import llm_post_auth_failure
    >>> llm_post_auth_failure(MagicMock(method="GET"), None) is None
    True
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse

_PROXY_TOKEN_HEADER = "x-sevn-proxy-token"  # nosec B105
_SESSION_TOKEN_HEADER = "x-sevn-session-token"  # nosec B105
_SESSION_TOKEN_VERSION = "v1"
_GUARDED_PREFIXES = ("/llm/", "/web/", "/integration/")
PROXY_UNCONFIGURED_DETAIL = "proxy authentication not configured"
SESSION_SCOPE_SANDBOX = "sandbox"
SESSION_SCOPE_LLM = "llm"
DEFAULT_SESSION_TOKEN_TTL_S = 3600


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


def _scope_allows_path(scope: str, path: str) -> bool:
    """Return whether a session-token scope covers ``path``.

    Args:
        scope (str): Token payload ``scope`` field.
        path (str): Request URL path.

    Returns:
        bool: ``True`` when the scope matches the route family.

    Examples:
        >>> _scope_allows_path("sandbox", "/web/fetch")
        True
        >>> _scope_allows_path("sandbox", "/llm/openai/chat/completions")
        False
        >>> _scope_allows_path("llm", "/llm/openai/chat/completions")
        True
    """
    if scope == SESSION_SCOPE_SANDBOX:
        return path == "/integration" or path.startswith("/web/")
    if scope == SESSION_SCOPE_LLM:
        return path.startswith("/llm/")
    return False


def mint_session_token(
    *,
    signing_key: str,
    scope: str,
    run_id: str,
    expires_at: int | None = None,
    ttl_s: int = DEFAULT_SESSION_TOKEN_TTL_S,
) -> str:
    """Mint a scoped per-run ``X-Sevn-Session-Token`` (D12).

    Args:
        signing_key (str): ``SEVN_PROXY_SHARED_SECRET`` used for HMAC signing.
        scope (str): Route-family scope (``sandbox`` or ``llm``).
        run_id (str): Correlation id embedded in the payload.
        expires_at (int | None): Unix expiry; defaults to ``now + ttl_s``.
        ttl_s (int): Seconds until expiry when ``expires_at`` is omitted.

    Returns:
        str: Token of the form ``v1.<payload>.<sig>``.

    Examples:
        >>> tok = mint_session_token(
        ...     signing_key="secret",
        ...     scope="sandbox",
        ...     run_id="run-1",
        ...     expires_at=9999999999,
        ... )
        >>> tok.startswith("v1.")
        True
    """
    exp = expires_at if expires_at is not None else int(time.time()) + ttl_s
    payload = {"scope": scope, "exp": exp, "run_id": run_id}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{_SESSION_TOKEN_VERSION}.{body}.{sig}"


def validate_session_token(
    token: str,
    *,
    signing_key: str,
    path: str,
    now: int | None = None,
) -> bool:
    """Verify signature, expiry, and route-family scope for a session token.

    Args:
        token (str): ``X-Sevn-Session-Token`` header value.
        signing_key (str): Expected ``SEVN_PROXY_SHARED_SECRET``.
        path (str): Request URL path being authorized.
        now (int | None): Current unix time; defaults to ``time.time()``.

    Returns:
        bool: ``True`` when the token is valid for ``path``.

    Examples:
        >>> tok = mint_session_token(
        ...     signing_key="k",
        ...     scope="sandbox",
        ...     run_id="r",
        ...     expires_at=9999999999,
        ... )
        >>> validate_session_token(tok, signing_key="k", path="/web/fetch")
        True
        >>> validate_session_token(tok, signing_key="k", path="/llm/openai/chat/completions")
        False
    """
    text = token.strip()
    if not text or not signing_key:
        return False
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != _SESSION_TOKEN_VERSION:
        return False
    body, sig = parts[1], parts[2]
    expected = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    padded = body + "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    scope = payload.get("scope")
    exp = payload.get("exp")
    if not isinstance(scope, str) or not isinstance(exp, int):
        return False
    ts = int(time.time()) if now is None else now
    if exp < ts:
        return False
    return _scope_allows_path(scope, path)


def llm_post_auth_failure(request: Request, proxy_shared_secret: str | None) -> JSONResponse | None:
    """Enforce ``X-Sevn-Proxy-Token`` or scoped ``X-Sevn-Session-Token`` on guarded routes.

    ``X-Sevn-Proxy-Token`` carries the long-lived gateway→proxy service secret and
    satisfies any guarded route. ``X-Sevn-Session-Token`` is a per-run scoped credential
    (``sandbox`` → ``/web/*`` + ``/integration``; ``llm`` → ``/llm/*``).

    When ``proxy_shared_secret`` is unset or empty, guarded routes return **503**
    unless ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` (explicit dev-only opt-in).

    Args:
        request (Request): ASGI request (path + method + headers).
        proxy_shared_secret (str | None): Expected service secret; unset fails closed.

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
    proxy_token = request.headers.get(_PROXY_TOKEN_HEADER)
    if hmac.compare_digest(proxy_token or "", proxy_shared_secret):
        return None
    session_token = request.headers.get(_SESSION_TOKEN_HEADER)
    if session_token and validate_session_token(
        session_token,
        signing_key=proxy_shared_secret,
        path=path,
    ):
        return None
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


__all__ = [
    "DEFAULT_SESSION_TOKEN_TTL_S",
    "PROXY_UNCONFIGURED_DETAIL",
    "SESSION_SCOPE_LLM",
    "SESSION_SCOPE_SANDBOX",
    "llm_post_auth_failure",
    "log_proxy_allow_unauthenticated_boot_warning",
    "mint_session_token",
    "proxy_allow_unauthenticated",
    "validate_session_token",
]
