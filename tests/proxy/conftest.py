"""Shared fixtures for egress proxy tests (fail-closed auth defaults)."""

from __future__ import annotations

from sevn.proxy.auth import SESSION_SCOPE_SANDBOX, mint_session_token
from sevn.proxy.settings import ProxySettings

PROXY_TEST_SECRET = "test"


def proxy_auth_headers(*, secret: str = PROXY_TEST_SECRET) -> dict[str, str]:
    """Return ``X-Sevn-Proxy-Token`` headers for guarded-route requests."""
    return {"X-Sevn-Proxy-Token": secret}


def merge_proxy_auth_headers(
    extra: dict[str, str] | None = None,
    *,
    secret: str = PROXY_TEST_SECRET,
) -> dict[str, str]:
    """Merge proxy auth headers with optional per-request headers."""
    headers = proxy_auth_headers(secret=secret)
    if extra:
        headers.update(extra)
    return headers


def proxy_test_settings(**kwargs: object) -> ProxySettings:
    """Build ``ProxySettings`` with a configured shared secret unless overridden."""
    data = dict(kwargs)
    if "proxy_shared_secret" not in data:
        data["proxy_shared_secret"] = PROXY_TEST_SECRET
    return ProxySettings(**data)


def integration_session_headers(
    *,
    secret: str = PROXY_TEST_SECRET,
    run_id: str = "run-integration-test",
) -> dict[str, str]:
    """Return sandbox-family auth headers for ``/integration`` and ``/web/*`` callers.

    Sandbox-originated families reject the service shared secret alone (D51 / C7.2);
    callers must present a freshly-minted scoped session token signed with the same
    secret, plus the run-id binding so the proxy can enforce C7.1.

    Args:
        secret (str): HMAC signing key (defaults to the proxy test secret).
        run_id (str): Synthetic run id embedded in the minted token.

    Returns:
        dict[str, str]: Combined ``X-Sevn-Proxy-Token`` + ``X-Sevn-Session-Token``
            + ``X-Sevn-Run-Id`` headers for sandbox-family requests.
    """
    token = mint_session_token(
        signing_key=secret,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
    )
    return {
        "X-Sevn-Proxy-Token": secret,
        "X-Sevn-Session-Token": token,
        "X-Sevn-Run-Id": run_id,
    }
