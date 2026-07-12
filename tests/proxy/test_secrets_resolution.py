"""Proxy ``${SECRET:…}`` expansion (``specs/06-secrets.md`` §9)."""

from __future__ import annotations

import pytest

from sevn.proxy.secrets_resolve import expand_secret_refs
from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain
from sevn.security.secrets.errors import SecretUnresolvedError


class _MemoryBackend:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.anyio
async def test_expand_secret_refs_substitutes() -> None:
    """``${SECRET:source:key}`` is replaced; ``${ENV:…}`` untouched."""
    b = _MemoryBackend()
    await b.set("providers.openai.api_key", "PLACEHOLDER_KEY")
    chain = SecretsChain([b], backend_labels=["encrypted_file"])
    cache = ResolvedSecretsCache(chain, ttl_seconds=0)
    raw = "pre ${SECRET:providers:providers.openai.api_key} mid ${ENV:HOME} post"
    out = await expand_secret_refs(raw, cache)
    assert "PLACEHOLDER_KEY" in out
    assert "${ENV:HOME}" in out


@pytest.mark.anyio
async def test_expand_secret_refs_unresolved_raises() -> None:
    """Missing secret raises ``SecretUnresolvedError``."""
    b = _MemoryBackend()
    chain = SecretsChain([b], backend_labels=["encrypted_file"])
    cache = ResolvedSecretsCache(chain, ttl_seconds=0)
    with pytest.raises(SecretUnresolvedError):
        await expand_secret_refs("${SECRET:x:missing.key}", cache)
