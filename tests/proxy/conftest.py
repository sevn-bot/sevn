"""Shared fixtures for egress proxy tests (fail-closed auth defaults)."""

from __future__ import annotations

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
