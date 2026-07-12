"""Gateway bearer + Telegram secret + Web UI JWT helpers
(`specs/17-gateway.md` §2.1, §6; `specs/19-channel-webui.md` §2.3-§2.5).

Module: sevn.gateway.auth
Depends: hmac, hashlib, base64, json, time, urllib.parse

Exports:
    JWTClaims — decoded Web UI JWT claim bundle.
    extract_bearer — parse ``Authorization`` header.
    secrets_compare — timing-safe equal-length string compare.
    verify_gateway_bearer — compare against configured token.
    verify_login_gateway_token — operator login body validation (§17 `/login`).
    login_page_html — minimal HTML shell for gateway bearer entry.
    verify_telegram_secret — webhook ``X-Telegram-Bot-Api-Secret-Token``.
    mint_webchat_jwt — HS256 JWT mint for ``aud=webchat`` (§2.3).
    verify_webchat_jwt — HS256 JWT verify, returns :class:`JWTClaims` or ``None``.
    refresh_webchat_access_token — mint a replacement JWT from claims or gateway bearer.
    verify_telegram_init_data — verify Telegram Web App ``initData`` HMAC (§2.5).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

_JWT_AUD: str = "webchat"
_JWT_ALG: str = "HS256"
_JWT_DEFAULT_SCOPE: tuple[str, ...] = ("session:read", "session:write")


@dataclass(frozen=True)
class JWTClaims:
    """Verified Web UI JWT claims (`specs/19-channel-webui.md` §2.3).

    Attributes:
        sub (str): Owner ``user_id`` or anonymous ``client_id`` prefix.
        aud (str): Always ``webchat`` after verify.
        exp (int): Expiry epoch seconds.
        scope (tuple[str, ...]): ``session:read`` / ``session:write``.
        iat (int): Issued-at epoch seconds (``0`` when absent).
    """

    sub: str
    aud: str
    exp: int
    scope: tuple[str, ...]
    iat: int = 0


def _b64url_encode(data: bytes) -> str:
    """Return URL-safe base64 without padding.

    Args:
        data (bytes): Raw bytes.

    Returns:
        str: ASCII string without trailing ``=``.

    Examples:
        >>> _b64url_encode(b"hi")
        'aGk'
    """

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token: str) -> bytes:
    """Decode URL-safe base64 padding back to bytes.

    Args:
        token (str): Base64URL string without padding.

    Returns:
        bytes: Decoded bytes.

    Examples:
        >>> _b64url_decode("aGk")
        b'hi'
    """

    pad = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode((token + pad).encode("ascii"))


def extract_bearer(authorization_header: str | None) -> str | None:
    """Return bearer token substring or ``None``.

    Args:
        authorization_header (str | None): Raw ``Authorization`` header.

    Returns:
        str | None: Bearer token text or ``None`` if absent / malformed.

    Examples:
        >>> extract_bearer("Bearer abc")
        'abc'
        >>> extract_bearer(None) is None
        True
    """

    if authorization_header is None:
        return None
    parts = authorization_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def secrets_compare(expected: str, received: str) -> bool:
    """Timing-safe compare for equal-length secrets.

    Args:
        expected (str): Configured value.
        received (str): Value from request.

    Returns:
        bool: ``True`` when equal byte-for-byte.

    Examples:
        >>> secrets_compare("a", "a")
        True
        >>> secrets_compare("a", "b")
        False
    """

    if len(expected) != len(received):
        return False
    return hmac.compare_digest(expected, received)


def verify_login_gateway_token(*, configured: str | None, submitted: str | None) -> bool:
    """Validate operator login token for ``POST /login`` (`specs/17-gateway.md` §2.1).

    When ``configured`` is unset (no gateway bearer enforcement), any non-empty
    submitted token is accepted so local dev can proceed to ``/webapp/``.

    Args:
        configured (str | None): Effective merged gateway token.
        submitted (str | None): Token from login form / JSON body.

    Returns:
        bool: ``True`` when login may proceed.

    Examples:
        >>> verify_login_gateway_token(configured="tok", submitted="tok")
        True
        >>> verify_login_gateway_token(configured="tok", submitted="bad")
        False
        >>> verify_login_gateway_token(configured=None, submitted="")
        False
        >>> verify_login_gateway_token(configured=None, submitted="any")
        True
    """

    if configured:
        if submitted is None:
            return False
        return secrets_compare(configured.strip(), submitted.strip())
    return bool(submitted and submitted.strip())


def login_page_html(*, gateway_auth_required: bool) -> str:
    """Return the operator login HTML shell served at ``GET /login``.

    Args:
        gateway_auth_required (bool): When ``True``, the form requires a bearer
            token before redirecting to ``/webapp/``.

    Returns:
        str: HTML document with inline script storing the token in
        ``sessionStorage`` under ``sevn.gateway_token``.

    Examples:
        >>> "sevn.gateway_token" in login_page_html(gateway_auth_required=True)
        True
    """

    hint = (
        "Gateway bearer token is required (set in sevn.json or SEVN_GATEWAY_TOKEN)."
        if gateway_auth_required
        else "No gateway bearer is configured — enter any non-empty label to continue."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>sevn.bot — login</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 28rem; margin: 3rem auto; padding: 0 1rem; }}
    label {{ display: block; margin: 0.5rem 0 0.25rem; }}
    input {{ width: 100%; padding: 0.5rem; font-size: 1rem; }}
    button {{ margin-top: 1rem; padding: 0.5rem 1rem; }}
    .err {{ color: #dc2626; }}
    .hint {{ color: #666; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <h1>sevn.bot login</h1>
  <p class="hint">{hint}</p>
  <form id="login">
    <label for="token">Gateway token</label>
    <input id="token" name="token" type="password" autocomplete="current-password" required />
    <button type="submit">Continue to webchat</button>
    <p id="err" class="err" hidden></p>
  </form>
  <script>
    document.getElementById("login").addEventListener("submit", async (ev) => {{
      ev.preventDefault();
      const token = document.getElementById("token").value.trim();
      const err = document.getElementById("err");
      err.hidden = true;
      const r = await fetch("/login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ token }}),
      }});
      if (!r.ok) {{
        err.textContent = "Login failed";
        err.hidden = false;
        return;
      }}
      sessionStorage.setItem("sevn.gateway_token", token);
      location.href = "/webapp/";
    }});
  </script>
</body>
</html>"""


def verify_gateway_bearer(*, configured: str | None, authorization_header: str | None) -> bool:
    """Return ``True`` when header matches configured token.

    Args:
        configured (str | None): Configured bearer or ``None`` to disable.
        authorization_header (str | None): Raw HTTP header.

    Returns:
        bool: Match result.

    Examples:
        >>> verify_gateway_bearer(configured="tok", authorization_header="Bearer tok")
        True
        >>> verify_gateway_bearer(configured="tok", authorization_header=None)
        False
        >>> verify_gateway_bearer(configured=None, authorization_header="Bearer tok")
        False
    """

    if not configured:
        return False
    expected = configured.strip()
    token = extract_bearer(authorization_header)
    if token is None:
        return False
    return secrets_compare(expected, token)


def verify_telegram_secret(*, configured: str | None, header_value: str | None) -> bool:
    """Match Telegram webhook secret token header.

    Args:
        configured (str | None): Configured secret or ``None``.
        header_value (str | None): Inbound ``X-Telegram-Bot-Api-Secret-Token``.

    Returns:
        bool: ``True`` when the secret matches (or unconfigured).

    Examples:
        >>> verify_telegram_secret(configured="s", header_value="s")
        True
        >>> verify_telegram_secret(configured="s", header_value=None)
        False
        >>> verify_telegram_secret(configured=None, header_value=None)
        True
    """

    if not configured:
        return True
    if header_value is None:
        return False
    return secrets_compare(configured.strip(), header_value.strip())


def mint_webchat_jwt(
    *,
    secret: str,
    sub: str,
    ttl_seconds: int,
    scope: tuple[str, ...] | list[str] | None = None,
    now: int | None = None,
) -> tuple[str, int]:
    """Mint an HS256 JWT for ``aud=webchat`` (`specs/19-channel-webui.md` §2.3).

    The token has compact ``header.payload.signature`` shape with
    base64url-encoded JSON segments and an HMAC-SHA256 signature over
    ``f"{header}.{payload}"``. ``scope`` is encoded as a space-delimited
    string per common JWT practice.

    Args:
        secret (str): Shared HS256 signing secret.
        sub (str): Stable owner ``user_id`` or ``anon:…`` prefix.
        ttl_seconds (int): Lifetime in seconds (must be positive).
        scope (tuple[str, ...] | list[str] | None): Override scope; defaults to
            ``("session:read", "session:write")``.
        now (int | None): Override current epoch seconds (testing).

    Returns:
        tuple[str, int]: ``(token, expires_in_seconds)`` pair.

    Raises:
        ValueError: When ``secret`` is empty or ``ttl_seconds`` < 1.

    Examples:
        >>> tok, exp = mint_webchat_jwt(secret="k", sub="u", ttl_seconds=60, now=1000)
        >>> isinstance(tok, str) and exp == 60
        True
    """

    if not secret:
        msg = "mint_webchat_jwt requires a non-empty secret"
        raise ValueError(msg)
    if ttl_seconds < 1:
        msg = "mint_webchat_jwt requires ttl_seconds >= 1"
        raise ValueError(msg)
    issued = int(now if now is not None else time.time())
    expiry = issued + int(ttl_seconds)
    scope_list = list(scope) if scope is not None else list(_JWT_DEFAULT_SCOPE)
    header = {"alg": _JWT_ALG, "typ": "JWT"}
    payload = {
        "sub": sub,
        "aud": _JWT_AUD,
        "iat": issued,
        "exp": expiry,
        "scope": " ".join(scope_list),
    }
    enc_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    enc_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{enc_header}.{enc_payload}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    enc_sig = _b64url_encode(sig)
    return f"{enc_header}.{enc_payload}.{enc_sig}", int(ttl_seconds)


def verify_webchat_jwt(
    *,
    secret: str,
    token: str,
    now: int | None = None,
) -> JWTClaims | None:
    """Verify HS256 JWT minted by :func:`mint_webchat_jwt`.

    Args:
        secret (str): Shared HS256 signing secret.
        token (str): JWT compact serialisation.
        now (int | None): Override current epoch seconds (testing).

    Returns:
        JWTClaims | None: Parsed claims when signature, ``aud``, and ``exp``
        all validate; ``None`` on any failure (no exceptions raised to the
        caller).

    Examples:
        >>> tok, _ = mint_webchat_jwt(secret="k", sub="u", ttl_seconds=60, now=1000)
        >>> verify_webchat_jwt(secret="k", token=tok, now=1010).sub
        'u'
        >>> verify_webchat_jwt(secret="k", token=tok, now=2000) is None
        True
        >>> verify_webchat_jwt(secret="k", token="bad.token", now=1010) is None
        True
    """

    if not secret or not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    enc_header, enc_payload, enc_sig = parts
    signing_input = f"{enc_header}.{enc_payload}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided_sig = _b64url_decode(enc_sig)
    except (ValueError, binascii.Error):
        return None
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None
    try:
        header = json.loads(_b64url_decode(enc_header).decode("utf-8"))
        payload = json.loads(_b64url_decode(enc_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(header, dict) or header.get("alg") != _JWT_ALG:
        return None
    if not isinstance(payload, dict):
        return None
    aud = payload.get("aud")
    sub = payload.get("sub")
    exp = payload.get("exp")
    if aud != _JWT_AUD or not isinstance(sub, str) or not isinstance(exp, int):
        return None
    current = int(now if now is not None else time.time())
    if current >= int(exp):
        return None
    raw_scope = payload.get("scope", "")
    scope_tuple: tuple[str, ...]
    if isinstance(raw_scope, str):
        scope_tuple = tuple(s for s in raw_scope.split() if s)
    elif isinstance(raw_scope, list):
        scope_tuple = tuple(str(s) for s in raw_scope if isinstance(s, str) and s)
    else:
        scope_tuple = ()
    iat_raw = payload.get("iat", 0)
    iat_int = int(iat_raw) if isinstance(iat_raw, int) else 0
    return JWTClaims(sub=sub, aud=str(aud), exp=int(exp), scope=scope_tuple, iat=iat_int)


def refresh_webchat_access_token(
    *,
    secret: str,
    ttl_seconds: int,
    authorization_header: str | None,
    gateway_configured: str | None,
    default_sub: str = "owner",
) -> tuple[str, int, str] | None:
    """Mint a fresh webchat JWT from an existing webchat or gateway bearer.

    Used by ``POST /auth/refresh`` (`specs/19-channel-webui.md` §2.3). Accepts
    either ``Authorization: Bearer <webchat_jwt>`` or a valid gateway bearer when
    ``gateway_configured`` is set.

    Args:
        secret (str): HS256 signing secret.
        ttl_seconds (int): New token lifetime.
        authorization_header (str | None): Raw ``Authorization`` header.
        gateway_configured (str | None): Effective gateway bearer for operator refresh.
        default_sub (str): ``sub`` when refreshing via gateway bearer only.

    Returns:
        tuple[str, int, str] | None: ``(access_token, expires_in, sub)`` or ``None``.

    Examples:
        >>> tok, _exp_in = mint_webchat_jwt(secret="k", sub="u", ttl_seconds=3600)
        >>> out = refresh_webchat_access_token(
        ...     secret="k",
        ...     ttl_seconds=60,
        ...     authorization_header=f"Bearer {tok}",
        ...     gateway_configured=None,
        ... )
        >>> out is not None
        True
    """

    bearer = extract_bearer(authorization_header)
    if bearer:
        claims = verify_webchat_jwt(secret=secret, token=bearer)
        if claims is not None:
            token, expires_in = mint_webchat_jwt(
                secret=secret,
                sub=claims.sub,
                ttl_seconds=ttl_seconds,
            )
            return token, expires_in, claims.sub
        if gateway_configured and secrets_compare(gateway_configured.strip(), bearer):
            token, expires_in = mint_webchat_jwt(
                secret=secret,
                sub=default_sub,
                ttl_seconds=ttl_seconds,
            )
            return token, expires_in, default_sub
    return None


def verify_telegram_init_data(
    *,
    bot_token: str,
    init_data: str,
    max_age_seconds: int | None = None,
    now: int | None = None,
) -> dict[str, str] | None:
    """Verify Telegram Web App ``initData`` HMAC (`specs/19-channel-webui.md` §2.5).

    Implements the documented Telegram check:

    1. Parse the form-encoded ``initData`` string.
    2. Build ``data_check_string`` from sorted ``key=value`` pairs excluding ``hash``.
    3. ``secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)``.
    4. Expected hash = ``HMAC_SHA256(key=secret_key, msg=data_check_string)``.
    5. Compare with the provided ``hash`` field using ``hmac.compare_digest``.

    Optionally rejects payloads older than ``max_age_seconds`` based on the
    ``auth_date`` field. The raw ``initData`` is never logged by callers
    (gateway error path emits only ``gateway.webapp.telegram_verify_failed``).

    Args:
        bot_token (str): Resolved Telegram bot token.
        init_data (str): Form-encoded payload as sent by the Web App SDK.
        max_age_seconds (int | None): Optional freshness window.
        now (int | None): Override current epoch seconds (testing).

    Returns:
        dict[str, str] | None: Parsed fields (including ``hash``) when valid;
        ``None`` on any verification failure.

    Examples:
        >>> verify_telegram_init_data(bot_token="", init_data="") is None
        True
        >>> verify_telegram_init_data(bot_token="x", init_data="hash=xx", now=1) is None
        True
    """

    if not bot_token or not init_data:
        return None
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            return None
        fields[key] = value
    provided = fields.pop("hash", None)
    if not provided:
        return None
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hex = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_hex, provided):
        return None
    if max_age_seconds is not None:
        auth_date_raw = fields.get("auth_date")
        if not auth_date_raw:
            return None
        try:
            auth_date = int(auth_date_raw)
        except ValueError:
            return None
        current = int(now if now is not None else time.time())
        if current - auth_date > int(max_age_seconds):
            return None
    fields["hash"] = provided
    return fields
