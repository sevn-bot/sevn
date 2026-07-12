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
    """Return True when ``POST /api/v1/run`` expects an ``Authorization`` header.

    Args:
        gateway_token (str | None): Effective gateway bearer when configured.
        webchat_jwt_secret (str | None): Webchat JWT signing secret when configured.

    Returns:
        bool: ``False`` only when neither credential surface is configured.

    Examples:
        >>> triggers_api_auth_required(gateway_token=None, webchat_jwt_secret=None)
        False
        >>> triggers_api_auth_required(gateway_token="tok", webchat_jwt_secret=None)
        True
    """
    if gateway_token and gateway_token.strip():
        return True
    return bool(webchat_jwt_secret and webchat_jwt_secret.strip())


def verify_triggers_api_bearer(
    *,
    authorization_header: str | None,
    gateway_token: str | None,
    webchat_jwt_secret: str | None,
) -> bool:
    """Verify gateway bearer or webchat JWT for triggers HTTP API routes.

    When no gateway token and no webchat JWT secret are configured, auth is
    disabled (dev laptops). Otherwise accept either the configured gateway
    bearer or a valid ``aud=webchat`` JWT carrying ``session:read`` and/or
    ``session:write`` — the same scope model as ``channels.webchat.public``.

    Args:
        authorization_header (str | None): Raw ``Authorization`` header value.
        gateway_token (str | None): Effective gateway bearer when configured.
        webchat_jwt_secret (str | None): Webchat JWT signing secret when configured.

    Returns:
        bool: ``True`` when the caller is authorized or auth is disabled.

    Examples:
        >>> verify_triggers_api_bearer(
        ...     authorization_header=None,
        ...     gateway_token=None,
        ...     webchat_jwt_secret=None,
        ... )
        True
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
        return True

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
            allowed = set(TRIGGERS_API_OPENAPI_BEARER_SCOPES)
            if allowed.intersection(claims.scope):
                return True
    return False


__all__ = [
    "TRIGGERS_API_OPENAPI_BEARER_SCOPES",
    "triggers_api_auth_required",
    "verify_triggers_api_bearer",
]
