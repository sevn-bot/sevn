"""Regression: resolved OAuth-shaped blobs never appear in logs (``specs/06-secrets.md`` §7)."""

from __future__ import annotations

import json
import logging

import pytest

from sevn.proxy.secrets_resolve import expand_secret_refs
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain


class _Mem:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = data

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


@pytest.mark.anyio
async def test_logs_never_contain_raw_oauth(caplog: pytest.LogCaptureFixture) -> None:
    """Secret resolution paths must not emit access/refresh token material to logs."""
    access = "sevn_oauth_leak_probe_access_9f2c1a"
    refresh = "sevn_oauth_leak_probe_refresh_8b1d0e"
    oauth_json = json.dumps(
        {"access_token": access, "refresh_token": refresh, "expires_at": "2026-01-01T00:00:00Z"},
    )
    backend = _Mem({"oauth.openai": oauth_json})
    chain = SecretsChain([backend], backend_labels=["m"])
    cache = ResolvedSecretsCache(chain, ttl_seconds=0)

    loggers = (
        "sevn.security.secrets",
        "sevn.security.secrets.chain",
        "sevn.security.secrets.cache",
        "sevn.security.secrets.backends",
        "sevn.proxy.secrets_resolve",
    )
    for name in loggers:
        logging.getLogger(name).setLevel(logging.DEBUG)

    caplog.set_level(logging.DEBUG)
    out = await expand_secret_refs(
        "prefix ${SECRET:p:oauth.openai} suffix",
        cache,
    )
    assert access in out
    blob = caplog.text
    assert access not in blob
    assert refresh not in blob
