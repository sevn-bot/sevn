"""HMAC-signed OpenUI capability tokens (`specs/29-openui.md` §5.8, §3.1).

Module: sevn.ui.openui.tokens
Depends: hashlib, hmac, json, secrets, base64

Exports:
    sign_token — mint a URL-safe token for ``scope`` ``render`` or ``submit``.
    verify_token — validate signature, expiry, and scope; return payload dict.
    verify_token_status — same verification with explicit ``ok`` / ``expired`` / ``invalid``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sevn.ui.openui.models import OpenUIScope


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding.

    Args:
        data (bytes): Raw bytes to encode.

    Returns:
        str: ASCII string safe for URL path segments.

    Examples:
        >>> _b64url(b"a")
        'YQ'
    """
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Inverse of :func:`_b64url` with implicit padding.

    Args:
        data (str): Stripped base64url text.

    Returns:
        bytes: Decoded payload.

    Examples:
        >>> _b64url_decode("YQ") == b"a"
        True
    """
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def sign_token(
    *,
    secret: str,
    workspace_id: str,
    session_id: str,
    message_id: str,
    record_id: str,
    scope: OpenUIScope,
    exp_unix: int,
) -> str:
    """Return an opaque URL token (payload + HMAC) for GET or POST scopes.

    Args:
        secret (str): Gateway signing material (never exposed to agents).
        workspace_id (str): Workspace identifier.
        session_id (str): Gateway session id.
        message_id (str): Correlates with executor turn / message.
        record_id (str): Store primary key for HTML retrieval.
        scope (OpenUIScope): ``render`` or ``submit``.
        exp_unix (int): Absolute expiry (Unix seconds).

    Returns:
        str: URL-safe token suitable for ``/openui/<token>`` or callback query.

    Examples:
        >>> t = sign_token(
        ...     secret="k",
        ...     workspace_id="w",
        ...     session_id="s",
        ...     message_id="m",
        ...     record_id="r",
        ...     scope="render",
        ...     exp_unix=2_000_000_000,
        ... )
        >>> isinstance(t, str) and "." in t
        True
    """

    payload: dict[str, Any] = {
        "v": 1,
        "wid": workspace_id,
        "sid": session_id,
        "mid": message_id,
        "rid": record_id,
        "scope": scope,
        "exp": int(exp_unix),
        "nonce": secrets.token_hex(8),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64url(body)
    sig = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64url(sig)}"


def verify_token(*, secret: str, token: str, expected_scope: OpenUIScope) -> dict[str, Any] | None:
    """Verify HMAC, expiry, and scope; return payload or ``None``.

    Args:
        secret (str): Same signing material used for :func:`sign_token`.
        token (str): Inbound token string.
        expected_scope (OpenUIScope): Required scope for this route.

    Returns:
        dict[str, Any] | None: Parsed payload on success; ``None`` on any failure.

    Examples:
        >>> secret = "s"
        >>> tok = sign_token(
        ...     secret=secret,
        ...     workspace_id="w",
        ...     session_id="s",
        ...     message_id="m",
        ...     record_id="r",
        ...     scope="render",
        ...     exp_unix=int(time.time()) + 3600,
        ... )
        >>> verify_token(secret=secret, token=tok, expected_scope="render") is not None
        True
        >>> verify_token(secret=secret, token=tok, expected_scope="submit") is None
        True
    """

    status, pl = verify_token_status(secret=secret, token=token, expected_scope=expected_scope)
    if status == "ok":
        return pl
    return None


def verify_token_status(
    *,
    secret: str,
    token: str,
    expected_scope: OpenUIScope,
) -> tuple[Literal["ok", "expired", "invalid"], dict[str, Any] | None]:
    """Like :func:`verify_token` but distinguishes expiry vs invalid (`specs/29-openui.md` §2.2).

    Args:
        secret (str): Same signing material used for :func:`sign_token`.
        token (str): Inbound token string.
        expected_scope (OpenUIScope): Required scope for this route.

    Returns:
        tuple[Literal["ok", "expired", "invalid"], dict[str, Any] | None]: Status tag plus
        payload when ``status == "ok"``.

    Examples:
        >>> import time
        >>> secret = "k"
        >>> tok = sign_token(
        ...     secret=secret,
        ...     workspace_id="w",
        ...     session_id="s",
        ...     message_id="m",
        ...     record_id="r",
        ...     scope="render",
        ...     exp_unix=int(time.time()) + 3600,
        ... )
        >>> verify_token_status(secret=secret, token=tok, expected_scope="render")[0]
        'ok'
    """

    if "." not in token:
        return "invalid", None
    body_b64, sig_b64 = token.split(".", 1)
    try:
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
    except (ValueError, OSError):
        return "invalid", None
    expect = hmac.new(secret.encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expect, sig):
        return "invalid", None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return "invalid", None
    if not isinstance(payload, dict):
        return "invalid", None
    if int(payload.get("v", 0)) != 1:
        return "invalid", None
    if payload.get("scope") != expected_scope:
        return "invalid", None
    exp = payload.get("exp")
    if not isinstance(exp, int):
        return "invalid", None
    if int(time.time()) > exp:
        return "expired", None
    for key in ("wid", "sid", "mid", "rid"):
        if not isinstance(payload.get(key), str) or not str(payload.get(key)).strip():
            return "invalid", None
    return "ok", payload


__all__ = ["sign_token", "verify_token", "verify_token_status"]
