"""Triggers API bearer verification (`specs/30-non-interactive-triggers.md` §2.2, §11).

Module: sevn.triggers.auth
Depends: sevn.gateway.auth

Exports:
    triggers_api_auth_required — whether callers must present credentials.
    verify_triggers_api_bearer — accept gateway bearer or ``aud=webchat`` JWT.
"""

from __future__ import annotations

from sevn.gateway.auth import extract_bearer, verify_gateway_bearer, verify_webchat_jwt

# Reuse webchat JWT scope strings — no separate OAuth machinery for ``/api/v1/run``.
TRIGGERS_API_OPENAPI_BEARER_SCOPES: tuple[str, ...] = ("session:read", "session:write")


def triggers_api_auth_required(
    *, gateway_token: str | None, webchat_jwt_secret: str | None
) -> bool:
    """Return True when triggers HTTP API routes expect an ``Authorization`` header.

    Args:
        gateway_token (str | None): Effective gateway bearer when configured.
        webchat_jwt_secret (str | None): Webchat JWT signing secret when configured.

    Returns:
        bool: Always ``True`` — triggers API auth is fail-closed even when secrets
        are unresolved at boot.

    Examples:
        >>> triggers_api_auth_required(gateway_token=None, webchat_jwt_secret=None)
        True
        >>> triggers_api_auth_required(gateway_token="tok", webchat_jwt_secret=None)
        True
    """
    _ = gateway_token, webchat_jwt_secret
    return True


TRIGGERS_API_WRITE_SCOPES: tuple[str, ...] = ("session:write",)


def verify_triggers_api_bearer(
    *,
    authorization_header: str | None,
    gateway_token: str | None,
    webchat_jwt_secret: str | None,
    require_write_scope: bool = False,
) -> bool:
    """Verify gateway bearer or webchat JWT for triggers HTTP API routes.

    Auth is always required. Accept the configured gateway bearer or a valid
    ``aud=webchat`` JWT. ``GET /runs/{id}`` accepts ``session:read`` or
    ``session:write``; ``POST /run`` requires ``session:write`` (or gateway bearer).

    Args:
        authorization_header (str | None): Raw ``Authorization`` header value.
        gateway_token (str | None): Effective gateway bearer when configured.
        webchat_jwt_secret (str | None): Webchat JWT signing secret when configured.
        require_write_scope (bool): When ``True``, JWT must include ``session:write``.

    Returns:
        bool: ``True`` when the caller is authorized.

    Examples:
        >>> verify_triggers_api_bearer(
        ...     authorization_header=None,
        ...     gateway_token=None,
        ...     webchat_jwt_secret=None,
        ... )
        False
        >>> verify_triggers_api_bearer(
        ...     authorization_header="Bearer nope",
        ...     gateway_token="secret",
        ...     webchat_jwt_secret=None,
        ... )
        False
    """
    if not triggers_api_auth_required(
        gateway_token=gateway_token,
        webchat_jwt_secret=webchat_jwt_secret,
    ):
        return False

    bearer = extract_bearer(authorization_header)
    if bearer is None:
        return False

    gw = gateway_token.strip() if gateway_token else None
    if gw and verify_gateway_bearer(configured=gw, authorization_header=authorization_header):
        return True

    secret = webchat_jwt_secret.strip() if webchat_jwt_secret else None
    if secret:
        claims = verify_webchat_jwt(secret=secret, token=bearer)
        if claims is not None and claims.aud == "webchat":
            if require_write_scope:
                return "session:write" in claims.scope
            allowed = set(TRIGGERS_API_OPENAPI_BEARER_SCOPES)
            if allowed.intersection(claims.scope):
                return True
    return False


__all__ = [
    "TRIGGERS_API_OPENAPI_BEARER_SCOPES",
    "TRIGGERS_API_WRITE_SCOPES",
    "triggers_api_auth_required",
    "verify_triggers_api_bearer",
]
