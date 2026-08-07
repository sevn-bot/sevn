"""Per-run destination allowlist and request/byte budgets for session tokens (C7.3).

Module: sevn.proxy.session_limits
Depends: sevn.proxy.auth (token envelope shape)

Budget state lives **in-process** on the proxy, keyed by token ``run_id``. A proxy
restart clears counters (W20.3 tradeoff: durable budgets need shared storage the
proxy does not yet have; silent reset is documented rather than pretended away).

Exports:
    DestinationNotAllowed — allowlist rejection.
    BudgetExceeded — request-count or byte budget exhaustion (not auth).
    destination_allowed — verify destination host against token allowlist.
    consume_run_budget — consume one request and ``request_bytes`` against the run.
    reset_run_budgets_for_tests — clear in-process counters (tests only).

Examples:
    >>> from sevn.proxy.session_limits import destination_allowed
    >>> destination_allowed.__name__
    'destination_allowed'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

_SESSION_TOKEN_VERSION = "v1"
_LOCK = threading.Lock()


class DestinationNotAllowed(Exception):
    """Raised when a destination host is outside the token allowlist."""


class BudgetExceeded(Exception):
    """Raised when a per-run request-count or byte budget is exhausted."""


@dataclass
class _RunBudgetState:
    """Mutable counters for one ``run_id`` (process-local)."""

    requests: int = 0
    bytes_used: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


_BUDGETS: dict[str, _RunBudgetState] = {}


def _verify_and_decode_payload(token: str, *, signing_key: str) -> dict[str, Any]:
    """Return the signed session-token payload or raise ``ValueError``.

    Args:
        token (str): ``v1.<payload>.<sig>`` session token.
        signing_key (str): HMAC signing key.

    Returns:
        dict[str, Any]: Decoded JSON payload.

    Raises:
        ValueError: When the token is malformed or the signature is wrong.

    Examples:
        >>> _verify_and_decode_payload.__name__
        '_verify_and_decode_payload'
    """
    text = token.strip()
    if not text or not signing_key:
        msg = "session token or signing key missing"
        raise ValueError(msg)
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != _SESSION_TOKEN_VERSION:
        msg = "malformed session token"
        raise ValueError(msg)
    body, sig = parts[1], parts[2]
    expected = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        msg = "invalid session token signature"
        raise ValueError(msg)
    padded = body + "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        msg = "invalid session token payload"
        raise ValueError(msg) from exc
    if not isinstance(payload, dict):
        msg = "session token payload must be an object"
        raise ValueError(msg)
    return payload


def destination_allowed(
    token: str,
    *,
    signing_key: str,
    destination: str,
) -> bool:
    """Return ``True`` when ``destination`` is permitted by the token allowlist.

    Tokens without an allowlist claim permit any destination (gateway-minted
    tokens that omit the claim). When the allowlist is present, the destination
    host must match an entry exactly (case-insensitive). The allowlist may be
    attached at the top level (``allowlist=[...]``) for backward compatibility
    with W20 test tokens, or under the unified ``limits`` envelope produced by
    the production mint (``limits.destinations=[...]``).

    Args:
        token (str): Signed session token carrying optional allowlist.
        signing_key (str): HMAC signing key.
        destination (str): Absolute URL whose host is checked.

    Returns:
        bool: ``True`` when allowed.

    Raises:
        DestinationNotAllowed: When the host is outside the allowlist.
        ValueError: When the token cannot be verified.

    Examples:
        >>> from sevn.proxy.auth import mint_session_token
        >>> # doctest uses product mint without allowlist → open
        >>> t = mint_session_token(
        ...     signing_key="k", scope="sandbox", run_id="r", expires_at=9999999999
        ... )
        >>> destination_allowed(t, signing_key="k", destination="https://a.example/")
        True
    """
    payload = _verify_and_decode_payload(token, signing_key=signing_key)
    limits = payload.get("limits")
    allowlist: object | None = None
    if isinstance(limits, dict):
        allowlist = limits.get("destinations")
    if allowlist is None:
        allowlist = payload.get("allowlist")
    if allowlist is None:
        return True
    if not isinstance(allowlist, list) or not all(isinstance(x, str) for x in allowlist):
        msg = "destination allowlist claim is invalid"
        raise DestinationNotAllowed(msg)
    host = (urlparse(destination.strip()).hostname or "").lower()
    if not host:
        msg = "destination URL missing host for allowlist check"
        raise DestinationNotAllowed(msg)
    allowed = {entry.strip().lower() for entry in allowlist if entry.strip()}
    if host not in allowed:
        msg = f"destination host {host!r} is not on the session allowlist"
        raise DestinationNotAllowed(msg)
    return True


def _budget_state_for(run_id: str) -> _RunBudgetState:
    """Return (creating if needed) the in-process budget counters for ``run_id``.

    Args:
        run_id (str): Session-token ``run_id`` claim.

    Returns:
        _RunBudgetState: Process-local counters for the run.

    Examples:
        >>> isinstance(_budget_state_for("run-doc"), _RunBudgetState)
        True
    """
    with _LOCK:
        state = _BUDGETS.get(run_id)
        if state is None:
            state = _RunBudgetState()
            _BUDGETS[run_id] = state
        return state


def consume_run_budget(
    token: str,
    *,
    signing_key: str,
    request_bytes: int,
) -> None:
    """Consume one request and ``request_bytes`` against the token's per-run budgets.

    Tokens without ``max_requests`` / ``max_bytes`` claims (or the unified
    ``limits.requests`` / ``limits.bytes`` envelope produced by the production
    mint) are unlimited. Exhaustion raises :class:`BudgetExceeded` (distinct
    from auth ``401``).

    Args:
        token (str): Signed session token carrying optional budget claims.
        signing_key (str): HMAC signing key.
        request_bytes (int): Byte size attributed to this request (body length).

    Returns:
        None: When the consume succeeds.

    Raises:
        BudgetExceeded: When the next request or byte total would exceed a limit.
        ValueError: When the token cannot be verified.

    Examples:
        >>> consume_run_budget.__name__
        'consume_run_budget'
    """
    payload = _verify_and_decode_payload(token, signing_key=signing_key)
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        msg = "session token missing run_id for budget tracking"
        raise BudgetExceeded(msg)
    limits = payload.get("limits")
    max_requests: object | None = None
    max_bytes: object | None = None
    if isinstance(limits, dict):
        max_requests = limits.get("requests")
        max_bytes = limits.get("bytes")
    if max_requests is None:
        max_requests = payload.get("max_requests")
    if max_bytes is None:
        max_bytes = payload.get("max_bytes")
    if max_requests is None and max_bytes is None:
        return
    if max_requests is not None and (
        not isinstance(max_requests, int) or isinstance(max_requests, bool) or max_requests < 0
    ):
        msg = "invalid max_requests budget claim"
        raise BudgetExceeded(msg)
    if max_bytes is not None and (
        not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0
    ):
        msg = "invalid max_bytes budget claim"
        raise BudgetExceeded(msg)
    nbytes = max(0, int(request_bytes))
    state = _budget_state_for(run_id)
    with state.lock:
        if max_bytes is not None and state.bytes_used + nbytes > max_bytes:
            msg = (
                f"byte budget exceeded for run {run_id!r}: "
                f"used={state.bytes_used} request={nbytes} max={max_bytes}"
            )
            raise BudgetExceeded(msg)
        if max_requests is not None and state.requests + 1 > max_requests:
            msg = (
                f"request budget exceeded for run {run_id!r}: "
                f"used={state.requests} max={max_requests}"
            )
            raise BudgetExceeded(msg)
        state.requests += 1
        state.bytes_used += nbytes


def reset_run_budgets_for_tests() -> None:
    """Clear in-process budget state (test helper only).

    Returns:
        None: Always ``None``.

    Examples:
        >>> reset_run_budgets_for_tests()
    """
    with _LOCK:
        _BUDGETS.clear()


__all__ = [
    "BudgetExceeded",
    "DestinationNotAllowed",
    "consume_run_budget",
    "destination_allowed",
    "reset_run_budgets_for_tests",
]
