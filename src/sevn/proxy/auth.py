"""Shared-secret and scoped session-token guard for proxy guarded routes.

Module: sevn.proxy.auth
Depends: starlette

Exports:
    llm_post_auth_failure — return a JSON error response when blocked, else ``None``.
    mint_session_token — mint a scoped per-run ``X-Sevn-Session-Token``.
    validate_session_token — verify signature, expiry, scope, and optional bindings.
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
_RUN_ID_HEADER = "x-sevn-run-id"
_CONTAINER_ID_HEADER = "x-sevn-container-id"
_SESSION_TOKEN_VERSION = "v1"  # nosec B105 — token format version label, not a credential
_GUARDED_PREFIXES = ("/llm/", "/web/", "/integration/")
_AUTH_CHECK_PATH = "/web/auth-check"
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
    import posixpath

    normalized = posixpath.normpath(path)
    if normalized in {"/web", "/llm"}:
        return True
    if normalized == "/integration":
        return True
    return any(normalized.startswith(prefix) for prefix in ("/llm/", "/web/", "/integration/"))


def _is_sandbox_route_family(path: str) -> bool:
    """Return whether ``path`` is a sandbox-originated route family (C7.2 / D51).

    Gateway→proxy LLM routes and the authenticated health probe are excluded so the
    service secret remains authoritative there. Sandbox families are ``/web/*``
    (except ``/web/auth-check``) and ``/integration``.

    Args:
        path (str): Request URL path.

    Returns:
        bool: ``True`` when the service shared secret must not authorize the path.

    Examples:
        >>> _is_sandbox_route_family("/web/fetch")
        True
        >>> _is_sandbox_route_family("/integration")
        True
        >>> _is_sandbox_route_family("/web/auth-check")
        False
        >>> _is_sandbox_route_family("/llm/openai/chat/completions")
        False
    """
    import posixpath

    normalized = posixpath.normpath(path)
    if normalized == _AUTH_CHECK_PATH:
        return False
    if normalized == "/integration" or normalized.startswith("/integration/"):
        return True
    return normalized == "/web" or normalized.startswith("/web/")


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


def _check_binding(
    *,
    claim_value: str,
    request_value: str,
    label: str,
) -> bool:
    """Return ``True`` when a token claim equals the request-attributed value.

    Helper for the proxy seam: the request side is always a real string (the
    proxy call site populates it from the header, falling back to an empty
    string when the header is absent). A token with a ``claim_value`` presented
    against a missing request-side binding is rejected — a missing header
    means a missing claim, not a free pass.

    Args:
        claim_value (str): Value embedded in the token payload.
        request_value (str): Request-attributed value resolved from headers.
        label (str): Human label used for log/error context.

    Returns:
        bool: ``True`` when the values match.

    Examples:
        >>> _check_binding(claim_value="run-a", request_value="run-a", label="run_id")
        True
        >>> _check_binding(claim_value="run-a", request_value="run-b", label="run_id")
        False
        >>> _check_binding(claim_value="ctr-a", request_value="", label="container_id")
        False
    """
    _ = label
    if not request_value:
        return False
    return hmac.compare_digest(claim_value, request_value)


def mint_session_token(
    *,
    signing_key: str,
    scope: str,
    run_id: str,
    container_id: str | None = None,
    destination_allowed: list[str] | None = None,
    request_budget: int | None = None,
    byte_budget: int | None = None,
    expires_at: int | None = None,
    ttl_s: int = DEFAULT_SESSION_TOKEN_TTL_S,
) -> str:
    """Mint a scoped per-run ``X-Sevn-Session-Token`` (D12 / C7.1, C7.3).

    Args:
        signing_key (str): ``SEVN_PROXY_SHARED_SECRET`` used for HMAC signing.
        scope (str): Route-family scope (``sandbox`` or ``llm``).
        run_id (str): Correlation id embedded in the payload.
        container_id (str | None): Optional spawning-container bind id (C7.1).
            A token minted without a ``container_id`` claim is not container-bound.
        destination_allowed (list[str] | None): Optional host allowlist claim
            (C7.3). When present, the proxy rejects outbound destinations whose
            host is not in this list. ``None`` (or omitted) emits no claim and
            the proxy does not enforce an allowlist.
        request_budget (int | None): Optional per-run request-count budget (C7.3).
            ``None`` (or omitted) emits no claim and the proxy does not enforce
            a request budget.
        byte_budget (int | None): Optional per-run byte budget (C7.3). ``None``
            (or omitted) emits no claim and the proxy does not enforce a byte
            budget.
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
    payload: dict[str, object] = {"scope": scope, "exp": exp, "run_id": run_id}
    if container_id is not None:
        payload["container_id"] = container_id
    if byte_budget is not None and (
        not isinstance(byte_budget, int) or isinstance(byte_budget, bool) or byte_budget < 0
    ):
        msg = "byte_budget must be a non-negative int"
        raise ValueError(msg)
    if request_budget is not None and (
        not isinstance(request_budget, int)
        or isinstance(request_budget, bool)
        or request_budget < 0
    ):
        msg = "request_budget must be a non-negative int"
        raise ValueError(msg)
    limits: dict[str, object] = {}
    if destination_allowed is not None:
        limits["destinations"] = list(destination_allowed)
    if request_budget is not None:
        limits["requests"] = int(request_budget)
    if byte_budget is not None:
        limits["bytes"] = int(byte_budget)
    if limits:
        payload["limits"] = limits
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
    run_id: str | None = None,
    container_id: str | None = None,
) -> bool:
    """Verify signature, expiry, route-family scope, and run/container binds.

    The ``run_id`` and ``container_id`` kwargs reflect the request-attributed
    binding values (the proxy resolves them from headers, defaulting to ``""``
    when a header is absent — never ``None``). When a binding is supplied:

    - if the token has a claim for it, the values must match (mismatch → reject);
    - if the token has no claim for it, the request still must not present a
      non-empty binding value (otherwise the token is being used outside the
      scope it was minted for).

    Passing ``None`` for ``run_id`` / ``container_id`` skips the binding check
    **only** on the low-level seam — unit paths that need to assert signature,
    expiry, or scope without exercising bindings. The proxy call site must
    always populate these kwargs with the resolved header (or ``""``), so a
    missing header is treated as a binding mismatch, not a free pass.

    Args:
        token (str): ``X-Sevn-Session-Token`` header value.
        signing_key (str): Expected ``SEVN_PROXY_SHARED_SECRET``.
        path (str): Request URL path being authorized.
        now (int | None): Current unix time; defaults to ``time.time()``.
        run_id (str | None): Request-attributed run id (``X-Sevn-Run-Id``).
        container_id (str | None): Request-attributed container bind id
            (``X-Sevn-Container-Id``).

    Returns:
        bool: ``True`` when the token is valid for ``path`` (and bindings).

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
    if not _scope_allows_path(scope, path):
        return False
    if run_id is not None:
        token_run_id = payload.get("run_id")
        if not isinstance(token_run_id, str) or not _check_binding(
            claim_value=token_run_id,
            request_value=run_id,
            label="run_id",
        ):
            return False
    if container_id is not None:
        token_cid = payload.get("container_id")
        if token_cid is not None:
            if not isinstance(token_cid, str) or not _check_binding(
                claim_value=token_cid,
                request_value=container_id,
                label="container_id",
            ):
                return False
        elif container_id:
            return False
    return True


def llm_post_auth_failure(
    request: Request,
    proxy_shared_secret: str | None,
    *,
    allow_unauthenticated: bool | None = None,
) -> JSONResponse | None:
    """Enforce ``X-Sevn-Proxy-Token`` or scoped ``X-Sevn-Session-Token`` on guarded routes.

    ``X-Sevn-Proxy-Token`` carries the long-lived gateway→proxy service secret and
    authorizes gateway→proxy families (``/llm/*``) plus the ``/web/auth-check`` probe.
    On sandbox-originated families (``/web/*`` except auth-check, ``/integration``) the
    service secret is **rejected** (C7.2 / D51); those paths require a session token.

    ``X-Sevn-Session-Token`` is a per-run scoped credential (``sandbox`` → ``/web/*`` +
    ``/integration``; ``llm`` → ``/llm/*``) optionally bound to ``X-Sevn-Run-Id`` and
    ``X-Sevn-Container-Id`` (C7.1).

    When ``proxy_shared_secret`` is unset or empty, guarded routes return **503**
    unless ``SEVN_PROXY_ALLOW_UNAUTHENTICATED=1`` (explicit dev-only opt-in).

    Args:
        request (Request): ASGI request (path + method + headers).
        proxy_shared_secret (str | None): Expected service secret; unset fails closed.
        allow_unauthenticated (bool | None): Override for ``SEVN_PROXY_ALLOW_UNAUTHENTICATED``;
            defaults to env when ``None``.

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
        unauth_ok = (
            proxy_allow_unauthenticated()
            if allow_unauthenticated is None
            else allow_unauthenticated
        )
        if unauth_ok:
            return None
        return JSONResponse({"detail": PROXY_UNCONFIGURED_DETAIL}, status_code=503)
    proxy_token = request.headers.get(_PROXY_TOKEN_HEADER)
    if hmac.compare_digest(proxy_token or "", proxy_shared_secret) and not _is_sandbox_route_family(
        path
    ):
        return None
    # Sandbox families: service secret alone is not authority (D51). A concurrent
    # session token (below) can still authorize the request.
    session_token = request.headers.get(_SESSION_TOKEN_HEADER)
    if session_token and validate_session_token(
        session_token,
        signing_key=proxy_shared_secret,
        path=path,
        run_id=request.headers.get(_RUN_ID_HEADER) or "",
        container_id=request.headers.get(_CONTAINER_ID_HEADER) or "",
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
