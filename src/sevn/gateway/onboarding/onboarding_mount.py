"""Mount onboarding wizard on the gateway (`specs/17-gateway.md`, `specs/22-onboarding.md`).

Exports:
    resolve_gateway_onboarding_token — env or ephemeral token for the wizard.
    mount_gateway_onboarding — attach ``/onboarding`` ASGI routes to the gateway app.
"""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI  # noqa: TC002

from sevn.onboarding.web_app import create_onboarding_app


def resolve_gateway_onboarding_token() -> str:
    """Return the onboarding capability token for gateway-mounted wizard routes.

    Returns:
        str: Token from ``SEVN_GATEWAY_ONBOARD_TOKEN`` or a freshly minted value.

    Examples:
        >>> tok = resolve_gateway_onboarding_token()
        >>> len(tok) >= 16
        True
    """
    env = os.environ.get("SEVN_GATEWAY_ONBOARD_TOKEN", "").strip()
    if env:
        return env
    return secrets.token_urlsafe(32)


def mount_gateway_onboarding(app: FastAPI, *, token: str) -> None:
    """Mount the loopback onboarding FastAPI app at ``/onboarding``.

    Args:
        app (FastAPI): Gateway application.
        token (str): ``onboard_token`` query/header value for protected routes.

    Returns:
        None: Routes are registered in-place.

    Examples:
        >>> from fastapi import FastAPI
        >>> g = FastAPI()
        >>> mount_gateway_onboarding(g, token="t")
        >>> any(getattr(r, "path", "") == "/onboarding" for r in g.routes)
        True
    """

    sub = create_onboarding_app(token)
    app.state.gateway_onboarding_token = token
    app.mount("/onboarding", sub)


__all__ = ["mount_gateway_onboarding", "resolve_gateway_onboarding_token"]
