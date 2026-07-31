"""W23.4 — secret precedence chain + provenance without values (#82 → W25)."""

from __future__ import annotations

import pytest

from sevn.security.secrets.chain import SecretsChain, get_secret_resilient


class _MemoryBackend:
    def __init__(self, label: str, values: dict[str, str] | None = None) -> None:
        self.label = label
        self.data: dict[str, str] = dict(values or {})

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.anyio
async def test_env_beats_chain_backend_for_same_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process env wins over every chain backend (deterministic precedence baseline)."""
    monkeypatch.setenv("MY_SECRET_KEY", "from-env")
    backend = _MemoryBackend("enc", {"MY_SECRET_KEY": "from-backend"})
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    assert await get_secret_resilient(chain, "MY_SECRET_KEY") == "from-env"


@pytest.mark.anyio
async def test_chain_backend_order_is_config_order() -> None:
    """First backend hit wins; earlier configured backends shadow later ones."""
    first = _MemoryBackend("macos_keychain", {"logical.key": "from-keychain"})
    second = _MemoryBackend("encrypted_file", {"logical.key": "from-file"})
    chain = SecretsChain([first, second], backend_labels=["macos_keychain", "encrypted_file"])
    assert await chain.get("logical.key") == "from-keychain"
    await first.delete("logical.key")
    assert await chain.get("logical.key") == "from-file"


@pytest.mark.anyio
async def test_resolve_secret_provenance_reports_backend_label() -> None:
    """Provenance names the winning source without returning the secret value."""
    from sevn.security.secrets.provenance import resolve_secret_provenance

    keychain = _MemoryBackend("macos_keychain")
    encrypted = _MemoryBackend("encrypted_file", {"providers.openai.api_key": "sk-live-value"})
    chain = SecretsChain([keychain, encrypted], backend_labels=["macos_keychain", "encrypted_file"])
    report = await resolve_secret_provenance(chain, "providers.openai.api_key")
    assert report.source == "encrypted_file"
    assert report.logical_key == "providers.openai.api_key"
    assert report.value is None
    assert "sk-live-value" not in repr(report)


@pytest.mark.anyio
async def test_provenance_cache_does_not_store_plaintext() -> None:
    """TTL cache retains resolved values but provenance snapshots exclude secrets."""
    from sevn.security.secrets.cache import ResolvedSecretsCache
    from sevn.security.secrets.provenance import provenance_for_cache_entry

    backend = _MemoryBackend("encrypted_file", {"gateway.token": "gw-top-secret"})
    chain = SecretsChain([backend], backend_labels=["encrypted_file"])
    cache = ResolvedSecretsCache(chain, ttl_seconds=60)
    await cache.get_resolved("gateway", "gateway.token")
    snapshot = provenance_for_cache_entry(cache, logical_key="gateway.token")
    assert snapshot.source == "encrypted_file"
    assert "gw-top-secret" not in str(snapshot)
